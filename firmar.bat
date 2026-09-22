@echo off
rem Firma LolcitoScout.exe con tu certificado de firma de código (por ejemplo Certum Open Source).
rem Antes: abrí SimplySign Desktop e iniciá sesión (así el certificado aparece en Windows).
rem Necesita signtool.exe (viene con el "Windows SDK": https://developer.microsoft.com/windows/downloads/windows-sdk/).
cd /d "%~dp0"
set NOMBRE=Open Source Developer, TU NOMBRE
signtool sign /n "%NOMBRE%" /fd sha256 /tr http://time.certum.pl /td sha256 /v LolcitoScout.exe
signtool verify /pa /v LolcitoScout.exe
pause
