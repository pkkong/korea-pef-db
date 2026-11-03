import Foundation
import AppKit
import PDFKit
import Vision
import CryptoKit

let maxBytes = 12 * 1024 * 1024
let maxPages = 12
let maxDimension = 1800
let maxPixels = 40_000_000
let engine = "macos-vision-r3-pdfkit-v1"

struct Failure: Error { let message: String }
func fail(_ message: String) throws -> Never { throw Failure(message: message) }
func run() throws {
    guard CommandLine.arguments.count == 2 else { try fail("expected one local PDF") }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
    guard let count = attrs[.size] as? NSNumber, count.intValue <= maxBytes else { try fail("PDF byte limit") }
    let raw = try Data(contentsOf: url, options: .mappedIfSafe)
    guard raw.count <= maxBytes, raw.starts(with: Data("%PDF-".utf8)),
          let pdf = PDFDocument(data: raw), !pdf.isEncrypted, !pdf.isLocked,
          pdf.pageCount > 0, pdf.pageCount <= maxPages else { try fail("unsupported PDF or page limit") }
    guard VNRecognizeTextRequest.supportedRevisions.contains(3) else { try fail("Vision revision 3 unavailable") }
    let languageProbe = VNRecognizeTextRequest()
    languageProbe.revision = 3
    languageProbe.recognitionLevel = .accurate
    let supported = try languageProbe.supportedRecognitionLanguages()
    let languages = ["ko-KR", "en-US"]
    guard languages.allSatisfy({ supported.contains($0) }) else { try fail("required OCR language unavailable") }
    var pages: [[String: Any]] = []
    var pixelCount = 0
    for index in 0..<pdf.pageCount {
        let result: [String: Any] = try autoreleasepool {
            guard let page = pdf.page(at: index) else { try fail("missing PDF page") }
            let bounds = page.bounds(for: .mediaBox)
            guard bounds.width.isFinite, bounds.height.isFinite, bounds.width > 0, bounds.height > 0,
                  max(bounds.width / bounds.height, bounds.height / bounds.width) <= 100 else { try fail("invalid page dimensions") }
            let scale = Double(maxDimension) / max(bounds.width, bounds.height)
            let width = max(1, Int(ceil(bounds.width * scale)))
            let height = max(1, Int(ceil(bounds.height * scale)))
            pixelCount += width * height
            guard pixelCount <= maxPixels else { try fail("PDF render pixel budget") }
            let thumbnail = page.thumbnail(of: NSSize(width: width, height: height), for: .mediaBox)
            var rect = NSRect(origin: .zero, size: thumbnail.size)
            guard let image = thumbnail.cgImage(forProposedRect: &rect, context: nil, hints: nil),
                  image.width <= maxDimension, image.height <= maxDimension else { try fail("PDF render failed or exceeded bounds") }
            let request = VNRecognizeTextRequest()
            request.revision = 3
            request.recognitionLevel = .accurate
            request.recognitionLanguages = languages
            request.automaticallyDetectsLanguage = false
            request.usesLanguageCorrection = false
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
            let observations = (request.results ?? []).sorted {
                // Fixed 1%-height reading rows; ties are ordered left to right.
                let row0 = Int(($0.boundingBox.midY * 100).rounded())
                let row1 = Int(($1.boundingBox.midY * 100).rounded())
                if row0 != row1 { return row0 > row1 }
                if $0.boundingBox.minX != $1.boundingBox.minX { return $0.boundingBox.minX < $1.boundingBox.minX }
                return ($0.topCandidates(1).first?.string ?? "") < ($1.topCandidates(1).first?.string ?? "")
            }
            var lines: [[String: Any]] = []
            for observation in observations {
                guard let candidate = observation.topCandidates(1).first else { continue }
                let b = observation.boundingBox
                lines.append(["text": candidate.string, "confidence": Double(candidate.confidence),
                              "bbox": [Double(b.minX), Double(b.minY), Double(b.width), Double(b.height)]])
            }
            return ["page": index + 1, "width": image.width, "height": image.height,
                    "lines": lines, "text": lines.map { $0["text"] as! String }.joined(separator: "\n")]
        }
        pages.append(result)
    }
    let sha = SHA256.hash(data: raw).map { String(format: "%02x", $0) }.joined()
    let result: [String: Any] = ["version": 1, "engine": engine, "revision": 3,
        "languages": languages, "input_sha256": sha, "input_bytes": raw.count,
        "os_version": ProcessInfo.processInfo.operatingSystemVersionString,
        "pages": pages]
    let encoded = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys, .withoutEscapingSlashes])
    guard encoded.count <= 8 * 1024 * 1024 else { try fail("OCR output byte limit") }
    FileHandle.standardOutput.write(encoded)
}
do { try run() }
catch let error as Failure {
    FileHandle.standardError.write(Data((error.message + "\n").utf8)); exit(1)
} catch {
    FileHandle.standardError.write(Data("local OCR failed\n".utf8)); exit(1)
}
