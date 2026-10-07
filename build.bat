@echo off
REM Builds a single-file Windows executable so the client can just
REM double-click it - no Python and no Tesseract install needed on their machine.
REM Run this from the project folder (the one containing main.py).
REM
REM Needs the "assets" folder (app_icon.ico, app_icon.png) next to main.py.
REM
REM For OCR to work without installing anything, put a copy of Tesseract in a
REM folder called "tesseract" next to main.py:
REM     tesseract\tesseract.exe
REM     tesseract\*.dll
REM     tesseract\tessdata\eng.traineddata
REM     tesseract\tessdata\osd.traineddata

REM Use the project's virtual environment if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo NOTE: no "venv" folder found - using whatever Python is on PATH.
)

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo FAILED: pip install did not complete successfully. See errors above.
    pause
    exit /b 1
)

REM ---- Bundle Tesseract if the folder is complete ----
set "TESS_ARG="
set "HAVE_TESS="
if exist tesseract\tesseract.exe if exist tesseract\tessdata\eng.traineddata if exist tesseract\tessdata\osd.traineddata set "HAVE_TESS=1"

if defined HAVE_TESS (
    echo Bundling Tesseract OCR into the .exe
    REM tesseract.exe needs the Microsoft Visual C++ runtime. A client PC may not
    REM have it installed, so ship copies next to tesseract.exe.
    for %%D in (vcruntime140.dll vcruntime140_1.dll msvcp140.dll msvcp140_1.dll msvcp140_2.dll concrt140.dll) do (
        if exist "%SystemRoot%\System32\%%D" if not exist "tesseract\%%D" copy /y "%SystemRoot%\System32\%%D" "tesseract\" >nul
    )
    set TESS_ARG=--add-data "tesseract;tesseract"
) else (
    echo.
    echo WARNING: bundled Tesseract not found or incomplete. It needs tesseract.exe,
    echo          tessdata\eng.traineddata and tessdata\osd.traineddata.
    echo          The .exe will be built WITHOUT built-in OCR.
    echo.
)

REM Remove old build output so stale files can't end up in the .exe
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist HSCodeChecker.spec del HSCodeChecker.spec

python -m PyInstaller --onefile --windowed --name "HSCodeChecker" ^
    --icon "assets\app_icon.ico" --add-data "assets;assets" ^
    --collect-all pdfplumber --collect-data pdfminer --collect-data certifi ^
    --hidden-import pytesseract %TESS_ARG% ^
    main.py
if errorlevel 1 (
    echo.
    echo FAILED: PyInstaller reported an error above. The .exe was NOT built.
    pause
    exit /b 1
)

echo.
echo Build succeeded. Find the .exe here: dist\HSCodeChecker.exe
pause