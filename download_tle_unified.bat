@echo off
rem ============================================================
rem  download_tle_unified.bat -- 每日 TLE 更新（Space-Track）＋重建 slim DB 與 parquet
rem
rem  用法：download_tle_unified.bat [publish]
rem    publish = 完成後接續執行 scenario-advanced01\update_slim_publish_hf.bat skipbuild
rem              併入 StoryMap TLE、上傳 HF Dataset、重啟兩個 Space
rem
rem  白名單不在此指定：由 prc_maneuver\build_slim_db.py 內建清單單一決定。
rem  注意：本檔以 CP950+CRLF 儲存；echo 行只用 ASCII，避免 Big5 尾位元組 0x5E 被 cmd 當成 ^ 續行。
rem ============================================================
setlocal
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo [%TIME:~0,8%] [1/2] Download TLE from Space-Track, rebuild slim DB and parquet ...
python download_TLE_unified.py --mode spacetrack --rebuild-slim --rebuild-parquet --keep-lines --recent-days 14
if errorlevel 1 goto :fail

if /i not "%~1"=="publish" (
  echo [%TIME:~0,8%] [2/2] skipped publish - run with "publish" to deploy to HF
  goto :ok
)
echo [%TIME:~0,8%] [2/2] Publish slim DB to HF ...
call "%~dp0scenario-advanced01\update_slim_publish_hf.bat" skipbuild
if errorlevel 1 goto :fail

:ok
echo [%TIME:~0,8%] [OK] done
exit /b 0
:fail
echo [FAIL] errorlevel %errorlevel% - aborted
exit /b 1
