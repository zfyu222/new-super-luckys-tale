    # This fragment runs inside the shared installer's lock, before any writes to game assets.
    $materialized=@{}
    $stageName='delta-'+[Guid]::NewGuid().ToString('N')
    $deltaStage=Within $stateDir $stageName
    $decoder=Within $PSScriptRoot 'xdelta3.exe'
    if((Digest $decoder) -ne $config.decoder_sha256) { throw '补丁工具不完整，请重新解压。' }
    $null=New-Item -ItemType Directory -Path $deltaStage
    foreach($file in $manifest.files) {
        $delta=Within $root $file.archive_path
        if((Digest $delta) -ne $file.delta_sha256) { throw '补丁文件不完整，请重新解压。' }
        $target=Within $root $file.path
        $current=Digest $target
        if($current -eq $file.sha256) { continue }
        $saved=Within $stateDir ('original/'+$file.path)
        if($current -eq $file.source_sha256) { $source=$target }
        elseif((Digest $saved) -eq $file.source_sha256) { $source=$saved }
        else { throw ('游戏资源版本不匹配：'+$file.path) }
        $slot=Within $deltaStage ([string]$materialized.Count)
        $null=New-Item -ItemType Directory -Path $slot
        # Native decoder receives ASCII relative names even in Unicode Steam library paths.
        $input=Within $slot 'original.bin'
        Copy-Item -LiteralPath $source -Destination $input
        Copy-Item -LiteralPath $delta -Destination (Within $slot 'patch.bin')
        $oldOptions=$env:XDELTA
        Push-Location -LiteralPath $slot
        try {
            $env:XDELTA=$null
            & $decoder -d -s original.bin patch.bin result.bin
            if($LASTEXITCODE -ne 0) { throw ('游戏资源重建失败：'+$file.path) }
        } finally {
            Pop-Location
            $env:XDELTA=$oldOptions
        }
        [IO.File]::Delete($input)
        $output=Within $slot 'result.bin'
        if((Digest $output) -ne $file.sha256) { throw ('重建校验失败：'+$file.path) }
        $materialized[$file.path]=$output
    }
