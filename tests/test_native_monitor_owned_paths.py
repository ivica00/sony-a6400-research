import unittest
from tools.research.run_native_monitor_sd_query import owned_paths
from tools.research import run_native_monitor_sd_journal as journal


class OwnedMonitorPaths(unittest.TestCase):
    def run_record(self):
        p='/tmp_bt/mon_sd_20261109_165636'
        return {'paths':{'binary':p+'.elf','log':p+'.log','receipt':p+'.log.receipt','stdout':p+'.stdout'}}

    def test_exact_run_paths(self):
        self.assertEqual(len(owned_paths(self.run_record())),4)

    def test_foreign_and_extra_paths_rejected(self):
        for key,value in [('binary','/tmp_bt/../etc/a.elf'),('receipt','/tmp_bt/foreign.log'),('other','/tmp_bt/other')]:
            with self.subTest(key=key):
                run=self.run_record();run['paths'][key]=value
                with self.assertRaises(ValueError):owned_paths(run)

    def test_mixed_run_rejected(self):
        run=self.run_record();run['paths']['log']=run['paths']['log'].replace('165636','165637')
        with self.assertRaises(ValueError):owned_paths(run)


class OwnedJournalPaths(unittest.TestCase):
    def run_record(self):
        p='/tmp_bt/mon_sd_20261109_172000'
        return {'paths':{'binary':p+'.elf','log':p+'.log','receipt':p+'.log.receipt','stdout':p+'.stdout','expected':p+'.expected'}}

    def test_exact_five_paths(self):
        self.assertEqual(len(journal.owned_paths(self.run_record())),5)

    def test_missing_mixed_or_extra_rejected(self):
        missing=self.run_record();del missing['paths']['expected']
        mixed=self.run_record();mixed['paths']['expected']=mixed['paths']['expected'].replace('172000','172001')
        extra=self.run_record();extra['paths']['other']='/tmp_bt/other'
        for name,run in [('missing',missing),('mixed',mixed),('extra',extra)]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):journal.owned_paths(run)

    def test_expected_pattern_is_bounded_deterministic_words(self):
        data=journal.expected_bytes()
        self.assertEqual(len(data),64)
        words=[int.from_bytes(data[i:i+8],'little') for i in range(0,64,8)]
        self.assertEqual(words,[journal.JOURNAL_IVAL+i for i in range(8)])
        self.assertEqual(journal.expected_bytes(),data)

    def test_journal_target_is_fixed_sd_path(self):
        self.assertEqual(journal.JOURNAL_PATH,'A:/A6400J.DAT')
