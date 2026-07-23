@echo off
rem =====================================================================
rem  리뷰봇 옛 예약작업 정리 스크립트 (집 PC / 매장 PC 각각 1회 실행)
rem  - 작업 스케줄러에서 review-digest / run.bat 관련 예약 작업 삭제
rem  - 시작프로그램 폴더의 관련 바로가기 삭제
rem  - 옛 review-digest 폴더를 찾아 run.bat 비활성화 (폴더는 직접 삭제)
rem  실행: 더블클릭. 삭제 실패 시 우클릭 → "관리자 권한으로 실행"
rem =====================================================================
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -Raw -Encoding UTF8 '%~f0') -split ('::PSBEGIN' + '::'),2)[1]"
echo.
pause
exit /b

::PSBEGIN::
$ErrorActionPreference = 'Continue'
Write-Host '=== 리뷰봇 옛 예약작업 정리 시작 ==='
Write-Host ''

$patterns = @('review-digest', 'run.bat', 'main.py')
$removedTasks = 0
$failedTasks = 0
$foundAny = $false

# ---- 1) 작업 스케줄러에서 관련 예약 작업 찾아 삭제 ----
$tasks = @()
try {
    $tasks = Get-ScheduledTask -ErrorAction Stop
} catch {
    Write-Host '[오류] 작업 스케줄러를 조회하지 못했습니다.'
    Write-Host '       이 창을 닫고, 파일을 우클릭 → "관리자 권한으로 실행"으로 다시 시도하세요.'
}
foreach ($t in $tasks) {
    $hit = $false
    foreach ($a in @($t.Actions)) {
        $s = "$($a.Execute) $($a.Arguments) $($a.WorkingDirectory)"
        foreach ($p in $patterns) {
            if ($s -and ($s -like "*$p*")) { $hit = $true }
        }
    }
    if ($hit) {
        $foundAny = $true
        Write-Host ("[발견] 예약 작업: {0}{1}" -f $t.TaskPath, $t.TaskName)
        try {
            Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false -ErrorAction Stop
            Write-Host '   → 삭제 완료'
            $removedTasks++
        } catch {
            Write-Host ("   → 삭제 실패: {0}" -f $_.Exception.Message)
            Write-Host '     파일을 우클릭 → "관리자 권한으로 실행"으로 다시 시도하세요.'
            $failedTasks++
        }
    }
}
if (-not $foundAny) {
    Write-Host '[확인] 작업 스케줄러에 리뷰봇 관련 예약 작업이 없습니다.'
}
Write-Host ''

# ---- 2) 시작프로그램 폴더의 관련 바로가기 삭제 ----
$startupDirs = @(
    [Environment]::GetFolderPath('Startup'),
    [Environment]::GetFolderPath('CommonStartup')
) | Where-Object { $_ -and (Test-Path $_) }
$shell = New-Object -ComObject WScript.Shell
$removedLinks = 0
foreach ($dir in $startupDirs) {
    foreach ($f in (Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue)) {
        $target = ''
        if ($f.Extension -eq '.lnk') {
            try { $target = $shell.CreateShortcut($f.FullName).TargetPath } catch { }
        }
        $s = "$($f.Name) $target"
        $hit = $false
        foreach ($p in $patterns) { if ($s -like "*$p*") { $hit = $true } }
        if ($hit) {
            Write-Host ("[발견] 시작프로그램 항목: {0}" -f $f.FullName)
            try {
                Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop
                Write-Host '   → 삭제 완료'
                $removedLinks++
            } catch {
                Write-Host ("   → 삭제 실패: {0}" -f $_.Exception.Message)
            }
        }
    }
}
if ($removedLinks -eq 0) {
    Write-Host '[확인] 시작프로그램에 리뷰봇 관련 항목이 없습니다.'
}
Write-Host ''

# ---- 3) 옛 review-digest 폴더 찾기 + run.bat 비활성화 ----
$bases = @(
    "$env:USERPROFILE\Desktop",
    "$env:USERPROFILE\OneDrive\Desktop",
    "$env:USERPROFILE\OneDrive\바탕 화면",
    "$env:OneDrive\Desktop",
    "$env:OneDrive\바탕 화면",
    "$env:USERPROFILE\Documents",
    "$env:USERPROFILE\Downloads"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
$folders = @()
foreach ($base in $bases) {
    $folders += Get-ChildItem -Path $base -Directory -Recurse -Depth 2 -Filter 'review-digest' -ErrorAction SilentlyContinue
}
$folders = $folders | Select-Object -Unique -ExpandProperty FullName
if ($folders.Count -eq 0) {
    Write-Host '[확인] 옛 review-digest 폴더를 찾지 못했습니다 (이미 지웠거나 다른 위치).'
} else {
    foreach ($dir in $folders) {
        Write-Host ("[발견] 옛 봇 폴더: {0}" -f $dir)
        foreach ($rb in (Get-ChildItem -Path $dir -Recurse -Depth 3 -Filter 'run.bat' -ErrorAction SilentlyContinue)) {
            try {
                Rename-Item -LiteralPath $rb.FullName -NewName 'run.bat.disabled' -Force -ErrorAction Stop
                Write-Host ("   → {0} 비활성화 완료" -f $rb.FullName)
            } catch {
                Write-Host ("   → run.bat 비활성화 실패: {0}" -f $_.Exception.Message)
            }
        }
        Write-Host '   → 이 폴더는 확인 후 휴지통으로 직접 삭제하세요 (.env 안에 옛 토큰이 남아 있습니다).'
    }
}

# ---- 요약 ----
Write-Host ''
Write-Host '========================================'
Write-Host ("결과: 예약 작업 {0}개 삭제, 시작프로그램 {1}개 삭제" -f $removedTasks, $removedLinks)
if ($failedTasks -gt 0) {
    Write-Host ("주의: 예약 작업 {0}개 삭제 실패 — 우클릭 → 관리자 권한으로 다시 실행하세요." -f $failedTasks)
} else {
    Write-Host '완료! 이제 이 컴퓨터에서는 리뷰봇이 몰래 실행되지 않습니다.'
}
Write-Host '집 PC와 매장 PC 각각에서 이 파일을 한 번씩 실행해야 합니다.'
Write-Host '========================================'
