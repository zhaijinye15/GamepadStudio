; Gamepad Studio 安装脚本（NSIS 3.x / Unicode）
; 构建：makensis -DOUTFILE=<输出路径> GamepadStudio.nsi
; 安装结构：
;   $INSTDIR\runtime      内嵌 Python 3.11 + site-packages
;   $INSTDIR\app          Gamepad Studio 源码包、字体、示例方案
;   $INSTDIR\tools        依赖自检脚本与 ViGEmBus 驱动安装包

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"

!define APP_NAME      "Gamepad Studio"
!define APP_NAME_CN   "手柄测试与映射"
!define APP_VERSION   "1.0.0"
!define APP_PUBLISHER "Gamepad Studio Project"
!define APP_URL       "https://github.com/"
!define UNINST_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\GamepadStudio"
!define UNINST_EXE    "uninstall.exe"

!ifndef OUTFILE
  !define OUTFILE "GamepadStudio-Setup-${APP_VERSION}.exe"
!endif
!ifndef PAYLOAD
  !define PAYLOAD "..\build\payload"
!endif

Name "${APP_NAME} ${APP_VERSION} · ${APP_NAME_CN}"
OutFile "${OUTFILE}"
InstallDir "$PROGRAMFILES64\Gamepad Studio"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
BrandingText "${APP_NAME} ${APP_VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey "FileVersion"     "${APP_VERSION}.0"
VIAddVersionKey "FileDescription" "${APP_NAME} 安装程序"
VIAddVersionKey "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright"  "MIT License"
VIAddVersionKey "Comments"        "手柄测试、按键映射与震动测试工具"

!define MUI_ICON   "assets/icon.ico"
!define MUI_UNICON "assets/icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "${APP_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将安装 ${APP_NAME} ${APP_VERSION}。$\r$\n$\r$\n包含：手柄测试台、按键映射、震动测试，以及运行所需的 Python 运行时与依赖库。$\r$\n$\r$\n点击「下一步」继续。"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "立即启动 ${APP_NAME}"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看使用说明"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION "OpenReadme"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; ----------------------------------------------------------------- 初始化
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "${APP_NAME} 需要 64 位 Windows 10/11。"
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

; ----------------------------------------------------------------- 安装段
Section "主程序（必需）" SEC_CORE
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetDetailsPrint both
  DetailPrint "正在部署 Python 运行时与依赖库…"
  File /r "${PAYLOAD}/runtime"
  DetailPrint "正在部署程序文件…"
  File /r "${PAYLOAD}/app"
  DetailPrint "正在部署维护工具…"
  File /r "${PAYLOAD}/tools"

  WriteUninstaller "$INSTDIR\${UNINST_EXE}"

  ; 依赖自检（失败也继续安装，引导用户用「依赖自检」快捷方式修复）
  DetailPrint "正在校验运行组件…"
  nsExec::ExecToStack '"$INSTDIR\runtime\python.exe" "$INSTDIR\tools\bootstrap.py" --quiet'
  Pop $0
  Pop $1
  ${If} $0 != 0
    DetailPrint "警告：依赖自检未通过（返回码 $0），可稍后运行「依赖自检」修复。"
  ${Else}
    DetailPrint "依赖自检通过。"
  ${EndIf}
SectionEnd

Section "桌面快捷方式" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\runtime\pythonw.exe" \
    '"$INSTDIR\app\run_gamepad.py"' "$INSTDIR\app\assets\icon.ico" 0 SW_SHOWNORMAL "" "${APP_NAME} · ${APP_NAME_CN}"
SectionEnd

Section "开始菜单" SEC_STARTMENU
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\runtime\pythonw.exe" \
    '"$INSTDIR\app\run_gamepad.py"' "$INSTDIR\app\assets\icon.ico" 0 SW_SHOWNORMAL "" "${APP_NAME} · ${APP_NAME_CN}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\依赖自检（修复）.lnk" "$INSTDIR\tools\check_env.bat" \
    "" "$INSTDIR\app\assets\icon.ico" 0 SW_SHOWNORMAL "" "校验并修复运行组件"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\使用说明.lnk" "$INSTDIR\app\docs\使用说明.html"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\${UNINST_EXE}"
SectionEnd

Section "ViGEmBus 虚拟手柄驱动" SEC_VIGEM
  DetailPrint "检查 ViGEmBus 驱动…"
  ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Services\ViGEmBus" "ImagePath"
  ${If} $0 == ""
    DetailPrint "未检测到 ViGEmBus，开始静默安装（需要管理员权限）…"
    nsExec::ExecToStack '"$INSTDIR\tools\ViGEmBus_Setup.exe" /quiet /norestart'
    Pop $0
    Pop $1
    ${If} $0 == 0
      DetailPrint "ViGEmBus 驱动安装完成。"
    ${ElseIf} $0 == 3010
      DetailPrint "ViGEmBus 驱动安装完成，需重启后生效。"
    ${Else}
      DetailPrint "ViGEmBus 安装返回码 $0，可稍后手动运行 tools\ViGEmBus_Setup.exe。"
    ${EndIf}
  ${Else}
    DetailPrint "已检测到 ViGEmBus，跳过安装。"
  ${EndIf}
SectionEnd

; ----------------------------------------------------------------- 描述
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE}      "程序本体、内嵌 Python 运行时与 pygame/hidapi 等依赖库，离线即可运行。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP}   "在桌面创建「${APP_NAME}」快捷方式，双击即可启动。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_STARTMENU} "创建开始菜单项，含依赖自检与使用说明入口。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_VIGEM}     "把真实手柄映射为虚拟 Xbox 360 / DualShock 4 手柄时需要；已安装则自动跳过。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ----------------------------------------------------------------- 收尾
Function LaunchApp
  Exec '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\app\run_gamepad.py"'
FunctionEnd

Function OpenReadme
  ExecShell "open" "$INSTDIR\app\docs\使用说明.html"
FunctionEnd

; ----------------------------------------------------------------- 卸载
Section "Uninstall"
  SetRegView 64
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\依赖自检（修复）.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\使用说明.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"

  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\tools"
  Delete "$INSTDIR\${UNINST_EXE}"
  Delete "$INSTDIR\*.log"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "${UNINST_KEY}"
  DeleteRegKey HKLM "Software\Classes\Applications\run_gamepad.py"

  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除用户配置与映射方案（%APPDATA%\GamepadStudio）？$\r$\n选择「否」将保留，便于重装后继续使用。" \
    /SD IDNO IDNO keep_profile
  RMDir /r "$APPDATA\GamepadStudio"
  keep_profile:

  DetailPrint "ViGEmBus 驱动属于共享组件，已保留。"
SectionEnd

; ----------------------------------------------------------------- 注册表
Function .onInstSuccess
  SetRegView 64
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME} · ${APP_NAME_CN}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\app\assets\icon.ico"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\${UNINST_EXE}"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINST_EXE}" /S'
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" "$0"
FunctionEnd
