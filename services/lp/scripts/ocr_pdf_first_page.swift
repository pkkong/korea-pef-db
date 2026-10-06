import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count == 2,
      let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])),
      let page = document.page(at: 0) else {
    fputs("PDF first page unavailable\n", stderr)
    exit(1)
}

let image = page.thumbnail(of: NSSize(width: 2200, height: 3100), for: .mediaBox)
var rectangle = CGRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &rectangle, context: nil, hints: nil) else {
    fputs("PDF first page image unavailable\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    for observation in request.results ?? [] {
        if let text = observation.topCandidates(1).first?.string {
            print(text)
        }
    }
} catch {
    fputs("PDF OCR failed: \(error)\n", stderr)
    exit(1)
}
