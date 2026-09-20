# 生成一段模拟面试对话音频，用于面经功能的端到端测试。
# 用系统自带的中文语音（Microsoft Huihui Desktop）。
# 刻意保留"嗯"等语气词，用来验证清洗环节是否真的生效。

Add-Type -AssemblyName System.Speech

$out = Join-Path $env:TEMP 'beibei-test-interview.wav'
if (Test-Path $out) { Remove-Item -LiteralPath $out -Force }

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Huihui Desktop')
$synth.Rate = 0

$turns = @(
    '你好，请先做一个自我介绍。',
    '面试官好，我叫张三，有三年 Java 后端开发经验，目前在一家电商公司负责订单系统。主要用的是 Spring Boot 和 MySQL，也接触过 Redis 和消息队列。',
    '那你介绍一下订单系统里最有挑战的一个问题。',
    '嗯，最麻烦的是大促期间的库存超卖。我们一开始是直接查数据库再更新，压测的时候发现并发下会超卖。后来改成用 Redis 的原子操作预扣库存，数据库只做最终落库。',
    '那 Redis 扣减和数据库不一致怎么办？',
    '我们用了本地消息表加定时补偿，如果落库失败就把 Redis 的扣减回滚。这个方案不完美，但比强一致方案简单很多。',
    '好的，你有什么想问我的吗？',
    '我想了解一下团队的技术栈和业务方向。'
)

$ssml = New-Object System.Text.StringBuilder
[void]$ssml.Append('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">')
for ($i = 0; $i -lt $turns.Count; $i++) {
    $text = [System.Security.SecurityElement]::Escape($turns[$i])
    [void]$ssml.Append("<s>$text</s>")
    # 轮次之间留 700ms 静音，便于按停顿切句
    if ($i -lt $turns.Count - 1) {
        [void]$ssml.Append('<break time="700ms"/>')
    }
}
[void]$ssml.Append('</speak>')

$synth.SetOutputToWaveFile($out)
$synth.SpeakSsml($ssml.ToString())
$synth.SetOutputToNull()
$synth.Dispose()

$info = Get-Item -LiteralPath $out
Write-Output ('生成: {0}' -f $out)
Write-Output ('大小: {0:N0} 字节' -f $info.Length)
