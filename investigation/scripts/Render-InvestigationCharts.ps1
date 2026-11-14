#requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$SpecPath,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$specs=Get-Content -LiteralPath $SpecPath -Raw -Encoding UTF8|ConvertFrom-Json
New-Item -ItemType Directory -Path $OutputDirectory -Force|Out-Null
$OutputDirectory=(Resolve-Path -LiteralPath $OutputDirectory).Path
function X-Value($value){
    if($value -is [DateTime]){$stamp=[DateTimeOffset]$value}else{$stamp=[DateTimeOffset]::Parse([string]$value,[Globalization.CultureInfo]::InvariantCulture)}
    $stamp.ToOffset([TimeSpan]::FromHours(5)).DateTime.ToOADate()
}
foreach($spec in $specs){
    $chart=New-Object System.Windows.Forms.DataVisualization.Charting.Chart
    try{
        $chart.Width=1500;$chart.Height=750;$chart.BackColor=[Drawing.Color]::White
        $chart.AntiAliasing='All';$chart.TextAntiAliasingQuality='High'
        $area=New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea('data')
        $area.Position=New-Object System.Windows.Forms.DataVisualization.Charting.ElementPosition(7,14,86,66)
        $area.BackColor=[Drawing.Color]::FromArgb(248,250,252)
        foreach($axis in @($area.AxisX,$area.AxisY)){
            $axis.LabelStyle.Font=New-Object Drawing.Font('Segoe UI',11)
            $axis.TitleFont=New-Object Drawing.Font('Segoe UI',12)
            $axis.MajorGrid.LineColor=[Drawing.Color]::FromArgb(220,226,234)
            $axis.LineColor=[Drawing.Color]::SlateGray
        }
        $area.AxisX.LabelStyle.Format='HH:mm:ss';$area.AxisX.Title=$spec.x_label
        $area.AxisX.IsMarginVisible=$false;$area.AxisY.Title=$spec.y_label
        $area.AxisY.Minimum=[double]$spec.y_min
        if($null -ne $spec.y_max){$area.AxisY.Maximum=[double]$spec.y_max}
        if($spec.y2_label){$area.AxisY2.Title=$spec.y2_label;$area.AxisY2.Minimum=0;$area.AxisY2.MajorGrid.Enabled=$false;$area.AxisY2.LabelStyle.Font=New-Object Drawing.Font('Segoe UI',11)}
        $chart.ChartAreas.Add($area)
        $legend=New-Object System.Windows.Forms.DataVisualization.Charting.Legend('targets')
        $legend.Docking='Bottom';$legend.Alignment='Center';$legend.Font=New-Object Drawing.Font('Segoe UI',11)
        $chart.Legends.Add($legend)
        $title=$chart.Titles.Add([string]$spec.title);$title.Font=New-Object Drawing.Font('Segoe UI',17,[Drawing.FontStyle]::Bold)
        $title.Position=New-Object System.Windows.Forms.DataVisualization.Charting.ElementPosition(3,2,94,8)
        foreach($item in $spec.series){
            $series=New-Object System.Windows.Forms.DataVisualization.Charting.Series([string]$item.name)
            $series.ChartType='Line';$series.BorderWidth=2;$series.Color=[Drawing.ColorTranslator]::FromHtml($item.color)
            $series.XValueType='DateTime';$series.ChartArea='data';$series.Legend='targets'
            if($spec.name -eq 'rtt-local-zoom.png'){
                $series.MarkerStyle='Circle';$series.MarkerSize=4
                if($item.name -eq $spec.series[0].name){$series.MarkerStyle='Square';$series.MarkerSize=8;$series.BorderWidth=3}
            }
            if($item.secondary){$series.YAxisType='Secondary'}
            foreach($point in $item.points){$null=$series.Points.AddXY((X-Value $point.x),[double]$point.y)}
            $chart.Series.Add($series)
        }
        if($spec.marker){
            $line=New-Object System.Windows.Forms.DataVisualization.Charting.StripLine
            $line.IntervalOffset=X-Value $spec.marker;$line.StripWidth=0;$line.BorderWidth=2
            $line.BorderColor=[Drawing.Color]::Gray;$line.BorderDashStyle='Dash';$line.Text=$spec.marker_text
            $area.AxisX.StripLines.Add($line)
        }
        $chart.SaveImage((Join-Path $OutputDirectory $spec.name),[System.Windows.Forms.DataVisualization.Charting.ChartImageFormat]::Png)
        Write-Output $spec.name
    }finally{$chart.Dispose()}
}
