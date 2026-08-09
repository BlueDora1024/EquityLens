import QtQuick
import ".."

Item {
    id: root
    property var points: []
    property string intervalLabel: ""

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.fillStyle = Theme.field
            ctx.fillRect(0, 0, width, height)
            if (!root.points || root.points.length === 0) {
                ctx.fillStyle = Theme.secondaryText
                ctx.font = "12px sans-serif"
                ctx.fillText("本次没有可绘制的历史图表数据", 18, height / 2)
                return
            }
            const top = Math.round(height * 0.66)
            let low = Number(root.points[0].low), high = Number(root.points[0].high)
            for (let i = 0; i < root.points.length; ++i) {
                low = Math.min(low, Number(root.points[i].low))
                high = Math.max(high, Number(root.points[i].high))
            }
            const span = Math.max(0.0001, high - low)
            const step = width / root.points.length
            const priceY = value => 16 + (high - value) / span * (top - 30)
            const priceText = value => Number(value).toFixed(Math.abs(value) >= 100 ? 2 : 3)
            const drawPriceGuide = (label, value) => {
                const y = priceY(value)
                ctx.strokeStyle = Theme.hairline
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke()
                const text = label + " " + priceText(value)
                ctx.font = "11px sans-serif"
                const labelWidth = ctx.measureText(text).width + 10
                const labelX = Math.max(4, width - labelWidth - 6)
                const labelY = Math.max(12, Math.min(top - 5, y + 4))
                ctx.fillStyle = Theme.field
                ctx.fillRect(labelX, labelY - 12, labelWidth, 16)
                ctx.fillStyle = Theme.secondaryText
                ctx.fillText(text, labelX + 5, labelY)
            }
            ctx.strokeStyle = Theme.hairline
            ctx.beginPath(); ctx.moveTo(0, top); ctx.lineTo(width, top); ctx.stroke()
            const zero = top + (height-top)/2
            ctx.strokeStyle = Theme.faintText
            ctx.beginPath(); ctx.moveTo(0, zero); ctx.lineTo(width, zero); ctx.stroke()
            drawPriceGuide("最高", high)
            drawPriceGuide("最低", low)
            let hasPressure = false
            for (let i = 0; i < root.points.length; ++i) {
                const point = root.points[i]
                const x = (i + .5) * step
                const up = Number(point.close) >= Number(point.open)
                ctx.strokeStyle = up ? Theme.success : Theme.danger
                ctx.fillStyle = ctx.strokeStyle
                ctx.beginPath(); ctx.moveTo(x, priceY(Number(point.high))); ctx.lineTo(x, priceY(Number(point.low))); ctx.stroke()
                const y1 = priceY(Math.max(Number(point.open), Number(point.close)))
                const y2 = priceY(Math.min(Number(point.open), Number(point.close)))
                ctx.fillRect(x - Math.max(1, step*.25), y1, Math.max(2, step*.5), Math.max(1, y2-y1))
                const buyRaw = Number(point.buyPressure || 0)
                const sellRaw = Number(point.sellPressure || 0)
                const buyVisual = Number(point.buyVisualStrength || 0)
                const sellVisual = Number(point.sellVisualStrength || 0)
                const half = (height-top)/2 - 8
                const buyY = zero + buyVisual / 100 * half
                const sellY = zero - sellVisual / 100 * half
                const barWidth = Math.max(2, step*.62)
                if (buyVisual > 0) {
                    ctx.fillStyle = Theme.success
                    ctx.fillRect(x - barWidth/2, zero, barWidth, buyY-zero)
                }
                if (sellVisual > 0) {
                    ctx.fillStyle = Theme.danger
                    ctx.fillRect(x - barWidth/2, sellY, barWidth, zero-sellY)
                }
                hasPressure = hasPressure || buyRaw > 0 || sellRaw > 0
            }
            ctx.fillStyle = Theme.secondaryText
            ctx.font = "11px sans-serif"
            ctx.fillText(root.intervalLabel + " · K 线 / 原始买卖压力（绿向下、红向上）", 12, 14)
            const startDate = String(root.points[0].timestamp || "").slice(0, 10)
            const endDate = String(root.points[root.points.length-1].timestamp || "").slice(0, 10)
            ctx.fillStyle = Theme.faintText
            ctx.fillText("开始 " + startDate, 12, height - 5)
            const endText = "结束 " + endDate
            ctx.fillText(endText, Math.max(12, width - ctx.measureText(endText).width - 12), height - 5)
            if (!hasPressure)
                ctx.fillText("本段没有触发买入或卖出压力", 12, zero - 8)
        }
    }
    onPointsChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
