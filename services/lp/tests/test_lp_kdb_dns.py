import json
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch
from services.lp.src import lp_kdb_dns as dns


def answer(name='www.kdb.co.kr.', kind=1, data='8.8.8.8'):
    return {'name':name, 'type':kind, 'TTL':60, 'data':data}


def response(answers=None):
    return {'Status':0,'TC':False,'CD':False,'AD':False,
            'Question':[{'name':'www.kdb.co.kr.','type':1}],
            'Answer':answers if answers is not None else [answer()]}


class KdbDnsTests(unittest.TestCase):
    def runner(self, raw=None, status=b'200', code=0):
        raw = json.dumps(response()).encode() if raw is None else raw
        def run(command, **kwargs):
            Path(command[command.index('--output')+1]).write_bytes(raw)
            return subprocess.CompletedProcess(command, code, status, b'SECRET stderr')
        return run

    def test_command_keeps_tls_fixed_dns_url_no_proxy_and_hard_deadline(self):
        with patch.object(dns.subprocess, 'run', side_effect=self.runner()) as run:
            rows=dns.resolve_kdb_ipv4(dns.HOST,443,2.5)
            self.assertEqual(rows,[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('8.8.8.8',443))])
            args=run.call_args.args[0]
            self.assertEqual(args[:2],['curl','--disable'])
            self.assertEqual(args[-1],dns.DNS_URL)
            for flag,value in [('--proxy',''),('--retry','0'),('--max-time','2.5'),('--proto','=https'),('--max-filesize',str(dns.MAX_BYTES))]:
                self.assertEqual(args[args.index(flag)+1],value)
            for forbidden in ['-k','--insecure','--location','-L','--resolve','--connect-to']:
                self.assertNotIn(forbidden,args)
            self.assertEqual(run.call_args.kwargs['timeout'],2.5)
            self.assertEqual(run.call_count,1)

    def test_only_exact_host_port_and_bounded_timeout(self):
        cases=[('other.example',443,5),(dns.HOST,80,5),(dns.HOST,'443',5),
               (dns.HOST,443,0),(dns.HOST,443,6),(dns.HOST,443,float('nan')),
               (dns.HOST,443,float('inf')),(dns.HOST,443,True)]
        with patch.object(dns.subprocess,'run') as run:
            for args in cases:
                with self.subTest(args=args),self.assertRaises(ValueError):dns.resolve_kdb_ipv4(*args)
            run.assert_not_called()

    def test_cname_chain_unsigned_zone_and_max_two_addresses(self):
        records=[answer(kind=5,data='edge.example.'),answer('edge.example.',5,'end.example.'),
                 answer('end.example.',data='8.8.8.8'),answer('end.example.',data='1.1.1.1'),answer('end.example.',data='9.9.9.9')]
        self.assertEqual(dns._addresses(json.dumps(response(records))),['1.1.1.1','8.8.8.8'])

    def test_bad_dns_envelope_and_question(self):
        cases=[]
        for field,value in [('Status',3),('Status',False),('TC',True),('CD',True),('Answer',[]),('Answer',[answer()]*33)]:
            data=response();data[field]=value;cases.append(data)
        for question in [[],[{'name':'foreign.example.','type':1}],[{'name':dns.HOST+'.','type':True}]]:
            data=response();data['Question']=question;cases.append(data)
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ValueError):dns._addresses(json.dumps(data))
        for raw in [b'{',b'\xff',b'{"Status":0,"Status":0}',b'null']:
            with self.assertRaises(ValueError):dns._addresses(raw)

    def test_unrelated_invalid_private_and_reserved_addresses_rejected(self):
        for value in ['127.0.0.1','10.0.0.1','169.254.169.254','224.0.0.1','240.0.0.1','0.0.0.0','100.64.0.1','192.0.2.1','::1','not-ip',134744072]:
            with self.subTest(value=value),self.assertRaises(ValueError):dns._addresses(json.dumps(response([answer(data=value)])))
        for records in [[answer(),answer('foreign.example.')],[answer(kind=28,data='::1')],
                        [{**answer(),'TTL':-1}],[{**answer(),'TTL':True}]]:
            with self.assertRaises(ValueError):dns._addresses(json.dumps(response(records)))

    def test_cname_loop_conflict_and_chain_budget(self):
        cases=[[answer(kind=5,data=dns.HOST+'.')],
               [answer(),answer(kind=5,data='edge.example.')],
               [answer(kind=5,data='one.example.'),answer(kind=5,data='two.example.')],
               [answer(kind=5,data='edge.example.'),answer('edge.example.',5,dns.HOST+'.')]]
        long=[answer(kind=5,data='n0.example.')]+[answer(f'n{i}.example.',5,f'n{i+1}.example.') for i in range(8)]+[answer('n8.example.')]
        cases.append(long)
        for records in cases:
            with self.assertRaises(ValueError):dns._addresses(json.dumps(response(records)))

    def test_native_http_tls_timeout_size_and_missing_output_fail_closed(self):
        for raw,status,code in [(b'',b'200',0),(b'x'*(dns.MAX_BYTES+1),b'200',0),
                                (b'{}',b'302',0),(b'{}',b'404',22),(b'{}',b'000',60),(b'{}',b'000',6)]:
            with patch.object(dns.subprocess,'run',side_effect=self.runner(raw,status,code)) as run:
                with self.assertRaises(ValueError) as caught:dns.resolve_kdb_ipv4(dns.HOST,443)
                self.assertNotIn('SECRET',str(caught.exception));self.assertEqual(run.call_count,1)
        for error in [FileNotFoundError('SECRET'),subprocess.TimeoutExpired('SECRET',5)]:
            with patch.object(dns.subprocess,'run',side_effect=error):
                with self.assertRaises(ValueError) as caught:dns.resolve_kdb_ipv4(dns.HOST,443)
                self.assertNotIn('SECRET',str(caught.exception))
        with patch.object(dns.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'200',b'')):
            with self.assertRaises(ValueError):dns.resolve_kdb_ipv4(dns.HOST,443)

if __name__=='__main__':unittest.main()
