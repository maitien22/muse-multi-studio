"""Windows executable entrypoint with crash diagnostics for windowed bootloader."""
import os
import tempfile
import traceback
from pathlib import Path

def main():
    try:
        from run import main as run_main
        run_main()
    except BaseException:
        root=Path(os.environ.get("MUSE_DATA_DIR") or tempfile.gettempdir())
        try:
            root.mkdir(parents=True,exist_ok=True)
            log=root/"startup-error.log"
            log.write_text(traceback.format_exc(),encoding="utf-8")
        except Exception:
            pass
        raise

if __name__=="__main__":
    main()
