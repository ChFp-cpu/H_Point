"""Backup verification must succeed before retention ever deletes old copies."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/backup-postgres.sh"


@unittest.skipUnless(os.name=="posix","POSIX backup script; exercised in Linux CI")
class BackupScript(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.app=self.base/"app";self.app.mkdir();(self.app/"compose.yaml").touch()
        self.backup=self.base/"backups";self.backup.mkdir()
        self.bin=self.base/"bin";self.bin.mkdir()
        fake=self.bin/"docker"
        fake.write_text('''#!/bin/sh
case "$*" in
 *pg_dump*) [ "$FAKE_DUMP_FAIL" != 1 ] || exit 8; printf 'verified-test-dump';;
 *pg_restore*) cat >/dev/null; [ "$FAKE_VERIFY_FAIL" != 1 ] || exit 9;;
 *) exit 10;;
esac
''');fake.chmod(0o700)
        self.env=dict(os.environ,PATH=str(self.bin)+os.pathsep+os.environ["PATH"],BACKUP_DIR=str(self.backup),BACKUP_RETENTION_DAYS="14",FAKE_DUMP_FAIL="0",FAKE_VERIFY_FAIL="0")
    def tearDown(self):self.temp.cleanup()
    def run_backup(self,**env):return subprocess.run(["sh",str(SCRIPT)],cwd=self.app,env={**self.env,**env},capture_output=True,text=True,timeout=10)
    def old(self):
        path=self.backup/"hpoint-20200101T000000Z.dump";path.write_text("old protected copy")
        os.utime(path,(time.time()-30*86400,)*2);return path
    def test_valid_archive_is_private_checksummed_then_rotated(self):
        old=self.old();unrelated=self.backup/"manual.dump";unrelated.write_text("keep")
        release=self.backup/"manual-release";release.mkdir()
        nested=release/"hpoint-20200101T000000Z.dump";nested.write_text("independently retained release")
        os.utime(nested,(time.time()-30*86400,)*2)
        result=self.run_backup();self.assertEqual(result.returncode,0,result.stderr)
        dumps=list(self.backup.glob("hpoint-*.dump"));self.assertEqual(len(dumps),1)
        self.assertFalse(old.exists());self.assertTrue(unrelated.exists())
        self.assertTrue(nested.exists())
        self.assertEqual(dumps[0].stat().st_mode&0o777,0o600)
        self.assertIn(hashlib.sha256(dumps[0].read_bytes()).hexdigest(),Path(str(dumps[0])+".sha256").read_text())
    def test_dump_or_verification_failure_never_rotates_or_publishes_partial(self):
        old=self.old()
        for key in ("FAKE_DUMP_FAIL","FAKE_VERIFY_FAIL"):
            with self.subTest(stage=key):
                self.assertNotEqual(self.run_backup(**{key:"1"}).returncode,0)
                self.assertEqual(list(self.backup.glob("*.dump")),[old])
                self.assertEqual(list(self.backup.glob("*.partial")),[])
    def test_rejects_checkout_parent_child_and_zero_retention_before_writes(self):
        for target in (self.app,self.app/"backups",self.base):
            with self.subTest(target=target):self.assertNotEqual(self.run_backup(BACKUP_DIR=str(target)).returncode,0)
        self.assertFalse((self.app/"backups").exists())
        for value in ("0","00","bad"):
            with self.subTest(retention=value):self.assertNotEqual(self.run_backup(BACKUP_RETENTION_DAYS=value).returncode,0)
        self.assertEqual(list(self.backup.iterdir()),[])

    def cron_installer(self):
        # Exercise the real installer with only its fixed deployment paths
        # translated into this disposable fixture. crontab is always mocked.
        installer=self.app/"install-backup-cron.sh"
        installer.write_text((SCRIPT.parent/"install-backup-cron.sh").read_text().replace("/opt/hpoint/H_Point",str(self.app)).replace("/opt/hpoint/backups/automatic",str(self.backup)))
        (self.app/"scripts").mkdir(exist_ok=True)
        (self.app/"scripts/backup-postgres.sh").touch()
        mock=self.bin/"crontab"
        mock.write_text('''#!/bin/sh
if [ "$1" = -l ]; then
 case "$FAKE_CRON_LIST" in
  missing) echo 'no crontab for synthetic' >&2; exit 1;;
  error) echo 'crontab: cannot read existing table' >&2; exit 2;;
  partial_error) cat "$FAKE_CRON_FILE"; echo 'crontab: interrupted listing' >&2; exit 2;;
  *) cat "$FAKE_CRON_FILE";;
 esac
else
 cp "$1" "$FAKE_CRON_FILE"
 printf installed > "$FAKE_CRON_INSTALLED"
fi
''');mock.chmod(0o700)
        return installer

    def run_installer(self,installer,mode="ok"):
        return subprocess.run(["sh",str(installer)],cwd=self.app,
            env={**self.env,"FAKE_CRON_LIST":mode,"FAKE_CRON_FILE":str(self.base/"crontab"),"FAKE_CRON_INSTALLED":str(self.base/"installed")},
            capture_output=True,text=True,timeout=10)

    def test_cron_installation_preserves_unrelated_jobs_and_is_idempotent(self):
        installer=self.cron_installer();table=self.base/"crontab"
        unrelated="7 2 * * * echo synthetic-unrelated\n"
        table.write_text(unrelated+"old managed line # hpoint-managed-backup\n")
        for _ in range(2):
            result=self.run_installer(installer);self.assertEqual(result.returncode,0,result.stderr)
        content=table.read_text()
        self.assertTrue(content.startswith(unrelated));self.assertEqual(content.count("# hpoint-managed-backup"),1)
        self.assertIn("15 * * * *",content)
        self.assertIn("BACKUP_DIR="+str(self.backup),content)

    def test_cron_listing_failure_never_overwrites_existing_or_partial_table(self):
        installer=self.cron_installer();table=self.base/"crontab"
        table.write_text("7 2 * * * echo synthetic-unrelated\n")
        before=table.read_bytes()
        for mode in ("error","partial_error"):
            with self.subTest(mode=mode):
                result=self.run_installer(installer,mode)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(table.read_bytes(),before)
                self.assertFalse((self.base/"installed").exists())
        self.assertEqual(self.run_installer(installer,"missing").returncode,0)
        self.assertEqual(table.read_text().count("# hpoint-managed-backup"),1)


if __name__=="__main__":unittest.main()
