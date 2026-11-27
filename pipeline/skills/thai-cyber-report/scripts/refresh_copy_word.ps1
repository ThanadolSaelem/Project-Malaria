param(
    [Parameter(Mandatory=$true)][string]$Docx,
    [Parameter(Mandatory=$true)][string]$Pdf
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $Docx).Path
$target = [IO.Path]::GetFullPath($Pdf)
if (Test-Path -LiteralPath $target) { throw 'PDF already exists. Use a new output path.' }
if ([IO.Path]::GetExtension($target) -ne '.pdf') { throw 'Output must be PDF.' }
$null = New-Item -ItemType Directory -Force ([IO.Path]::GetDirectoryName($target))
$word = $null
$document = $null
$originalPrintDrawings = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $originalPrintDrawings = $word.Options.PrintDrawingObjects
    $word.Options.PrintDrawingObjects = $true
    $document = $word.Documents.Open($source, $false, $false)
    $document.ActiveWindow.View.Type = 3
    $document.ActiveWindow.View.ShowAll = $true
    foreach ($section in $document.Sections) {
        foreach ($story in @($section.Headers) + @($section.Footers)) {
            foreach ($field in $story.Range.Fields) {
                if ($field.Type -in @(26, 33, 66)) { $field.Update() | Out-Null }
            }
        }
    }
    $document.Repaginate()
    foreach ($toc in $document.TablesOfContents) { $toc.UpdatePageNumbers() }; $document.Repaginate(); $document.Save(); $document.ExportAsFixedFormat($target, 17)
    Write-Output $target
} finally {
    if ($null -ne $document) { $document.Close(0); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($document) }
    if ($null -ne $word) {
        if ($null -ne $originalPrintDrawings) { $word.Options.PrintDrawingObjects = $originalPrintDrawings }
        $word.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
}

