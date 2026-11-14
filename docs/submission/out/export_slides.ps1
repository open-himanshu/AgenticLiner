$pptxPath = "C:\PROJECTS\AgenticLiner\docs\submission\out\OPEN_OUTLIERS_AgenticLiner.pptx"
$outDir = "C:\PROJECTS\AgenticLiner\docs\submission\out\slides_png"
if (!(Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$ppt = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $pres = $ppt.Presentations.Open($pptxPath, -1, 0, 0)
    for ($i = 1; $i -le $pres.Slides.Count; $i++) {
        $imgPath = Join-Path $outDir ("slide_{0}.png" -f $i)
        $pres.Slides.Item($i).Export($imgPath, "PNG", 1920, 1080)
        Write-Host "Exported slide $i to $imgPath"
    }
    $pres.Close()
} finally {
    $ppt.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
