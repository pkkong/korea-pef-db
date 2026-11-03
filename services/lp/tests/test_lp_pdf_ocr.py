import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from services.lp.src import lp_pdf_ocr as o

RAW=b'%PDF-1.7\nfixture'

def result():
    return {'version':1,'engine':o.ENGINE,'revision':3,'languages':['ko-KR','en-US'],
            'input_sha256':hashlib.sha256(RAW).hexdigest(),'input_bytes':len(RAW),'os_version':'test macOS',
            'pages':[{'page':1,'width':1200,'height':1800,'text':'국내 PE\n벤처 VC',
                      'lines':[{'text':'국내 PE','confidence':0.9,'bbox':[0.1,0.8,0.5,0.1]},
                               {'text':'벤처 VC','confidence':0.8,'bbox':[0.1,0.6,0.5,0.1]}]}]}


class PdfOcrTests(unittest.TestCase):
    def setUp(self):o._CACHE.clear();o._CACHE_BYTES=0
    def tearDown(self):o._CACHE.clear();o._CACHE_BYTES=0

    def test_valid_result_preserves_page_lines_and_identity(self):
        value=o.validate_result(result(),RAW,'a'*64)
        self.assertEqual(value['pages'][0]['text'],'국내 PE\n벤처 VC')
        self.assertEqual(value['helper_sha256'],'a'*64)

    def test_contract_corruption_and_language_fallback_rejected(self):
        for change in (lambda x:x.update(input_sha256='0'*64),lambda x:x.update(languages=['en-US']),
                       lambda x:x.update(revision=2),lambda x:x['pages'][0].update(page=2),
                       lambda x:x['pages'][0].update(width=1801),lambda x:x['pages'][0].update(text='changed'),
                       lambda x:x['pages'][0]['lines'][0].update(confidence=float('nan')),
                       lambda x:x['pages'][0]['lines'][0].update(bbox=[0,0,2,1])):
            value=result();change(value)
            with self.assertRaises(ValueError):o.validate_result(value,RAW,'a'*64)
        value=result();value['pages']*=13
        with self.assertRaises(ValueError):o.validate_result(value,RAW,'a'*64)

    def test_input_limits_and_non_macos_fail_before_execution(self):
        for raw in (b'notpdf',b'%PDF-'+b'a'*o.MAX_INPUT_BYTES,'text'):
            with self.assertRaises(ValueError):o.recognize_pdf(raw)
        with patch.object(o.platform,'system',return_value='Linux'),patch.object(o.subprocess,'run') as run:
            with self.assertRaises(ValueError):o._compiler()
            run.assert_not_called()

    def test_cache_only_verified_results_returns_defensive_copy(self):
        with patch.object(o,'_binary',return_value=Path('/tmp/fake')),patch.object(o,'_run',return_value=json.dumps(result()).encode()) as run:
            first=o.recognize_pdf(RAW);first['pages'][0]['text']='caller edit'
            second=o.recognize_pdf(RAW)
            self.assertEqual(second['pages'][0]['text'],'국내 PE\n벤처 VC')
            self.assertEqual(run.call_count,1)
            self.assertLessEqual(o._CACHE_BYTES,o.CACHE_LIMIT)
        o._CACHE.clear();o._CACHE_BYTES=0
        bad=result();bad['input_sha256']='0'*64
        with patch.object(o,'_binary',return_value=Path('/tmp/fake')),patch.object(o,'_run',return_value=json.dumps(bad).encode()):
            with self.assertRaises(ValueError):o.recognize_pdf(RAW)
        self.assertFalse(o._CACHE)

    def test_small_cache_does_not_store_and_invalid_json_fails(self):
        with patch.object(o,'CACHE_LIMIT',1),patch.object(o,'_binary',return_value=Path('/tmp/fake')),patch.object(o,'_run',return_value=json.dumps(result()).encode()):
            o.recognize_pdf(RAW);self.assertFalse(o._CACHE)
        with patch.object(o,'_binary',return_value=Path('/tmp/fake')),patch.object(o,'_run',return_value=b'{"confidence":NaN}'):
            with self.assertRaises(ValueError):o.recognize_pdf(RAW)

    def test_timeout_and_output_limit_fail_closed_without_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'out'
            with patch.object(o.subprocess,'run',side_effect=subprocess.TimeoutExpired('private source',1)):
                with self.assertRaisesRegex(ValueError,'timed out') as error:o._run(['helper'],path,1)
                self.assertNotIn('private source',str(error.exception))
            def excessive(*args,**kwargs):
                kwargs['stdout'].write(b'x'*11);return subprocess.CompletedProcess([],0)
            with patch.object(o,'MAX_OUTPUT_BYTES',10),patch.object(o.subprocess,'run',side_effect=excessive):
                with self.assertRaisesRegex(ValueError,'exceeded'):o._run(['helper'],path,1)

if __name__=='__main__':unittest.main()
