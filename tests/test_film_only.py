"""Regression checks against the mixed historical corpus; no external API calls."""
import json
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from app import main, knowledge_tree, embed


class FilmOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        cls.idx = main.INDEX
        with cls.idx.conn() as c:
            cls.fm = c.execute("SELECT file FROM papers WHERE category='film_motor' LIMIT 1").fetchone()[0]
            cls.ea = c.execute("SELECT file FROM papers WHERE category='electroadhesion' AND cross_topic=1 LIMIT 1").fetchone()[0]
            cls.expected = c.execute("SELECT COUNT(*) FROM papers WHERE category='film_motor'").fetchone()[0]
        cls.query_vec = cls.idx.vectors[0].copy()
        cls.mock = patch.object(embed, 'embed_query', return_value=cls.query_vec)
        cls.mock.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()
        cls.client.__exit__(None, None, None)

    def test_pages_and_legacy_routes(self):
        for url in ['/', '/fm', '/index.html', '/domain.html', '/fm/search', '/fm/learn']:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotIn('electroadhesion', r.text)
            self.assertNotIn('静电吸附', r.text)
        for url in ['/ea', '/ea/search', '/ea/learn']:
            self.assertEqual(self.client.get(url).status_code, 404)
        for old, new in [('/all','/fm'),('/all/search','/fm/search'),('/search','/fm/search'),('/learn','/fm/learn'),('/all/learn','/fm/learn')]:
            r=self.client.get(old, follow_redirects=False)
            self.assertEqual(r.status_code, 308)
            self.assertEqual(r.headers['location'], new)

    def test_statistics_and_tree(self):
        s=self.client.get('/api/stats').json()
        self.assertEqual(s['papers'], self.expected)
        self.assertEqual(s['chunks'], s['vectors'])
        self.assertEqual([x['key'] for x in s['categories']], ['film_motor'])
        for suffix in ['', '?domain=fm', '?domain=all']:
            o=self.client.get('/api/overview'+suffix).json()
            self.assertEqual(o['totals']['papers'], self.expected)
            self.assertLessEqual(o['totals']['geo_coverage'], self.expected)
            t=self.client.get('/api/tree'+suffix).json()
            self.assertEqual(t['id'], 'fm_root')
            self.assertTrue(all(n['id'].startswith('fm_') for n in knowledge_tree.walk(t)))
        for api in ['tree','overview','benchmarks']:
            self.assertEqual(self.client.get('/api/'+api+'?domain=ea').status_code,404)
        b=self.client.get('/api/benchmarks').json()
        self.assertTrue(all(p['category']=='film_motor' for m in b['metrics'].values() for p in m['points']))
        self.assertFalse({'normal_pressure','shear_stress','holding_force'} & b['metrics'].keys())

    def test_retrieval_cannot_escape_domain(self):
        for category in [None,'film_motor']:
            for fn in [self.idx.keyword_search,self.idx.vector_search]:
                ids=fn('electrostatic film motor',k=100,category=category)
                hits=self.idx._hydrate(ids,'motor')
                self.assertTrue(hits)
                self.assertTrue(all(h.category=='film_motor' for h in hits))
            r=self.client.post('/api/search',json={'query':'electrostatic motor','category':category,'expand':False})
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.json()['hits'])
            self.assertTrue(all(h['category']=='film_motor' for h in r.json()['hits']))
        for api in ['search','ask']:
            self.assertEqual(self.client.post('/api/'+api,json={'query':'x','category':'electroadhesion'}).status_code,422)
        self.assertEqual(self.client.get('/api/paper/'+self.ea).status_code,404)
        self.assertEqual(self.client.get('/api/pdf/'+self.ea).status_code,404)
        self.assertEqual(self.client.get('/api/paper/'+self.fm).status_code,200)

    def test_streaming_ask_and_learning(self):
        with patch.object(main.llm,'expand_query',side_effect=lambda q:q), patch.object(main.llm,'stream_chat',return_value=iter(['测试引用 [1]'])):
            r=self.client.post('/api/ask',json={'query':'electrostatic motor'})
            self.assertIn('event: done',r.text)
            events=[json.loads(x[6:]) for x in r.text.splitlines() if x.startswith('data: ')]
            self.assertTrue(all(h['category']=='film_motor' for e in events for h in e.get('hits',[])))
        with patch.object(main.llm,'chat',side_effect=RuntimeError('offline test')):
            r=self.client.post('/api/learn',json={'question':'electrostatic motor'})
            self.assertIn('event: done',r.text)
            self.assertNotIn('event: error',r.text)
            events=[json.loads(x[6:]) for x in r.text.splitlines() if x.startswith('data: ')]
            self.assertTrue(any('nodes' in e for e in events))
            self.assertTrue(all(n.startswith('fm_') for e in events for n in e.get('nodes',[])))
            self.assertTrue(all(p['category']=='film_motor' for e in events for p in e.get('papers',[])))
        self.assertEqual(self.client.post('/api/learn',json={'question':'x','domain':'ea'}).status_code,422)

if __name__=='__main__':
    unittest.main()
