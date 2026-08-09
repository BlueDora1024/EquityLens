import QtQuick
import ".."

Canvas {
    id: icon
    property color tint: Theme.accent

    implicitWidth: 12
    implicitHeight: 12
    width: 12
    height: 12
    onTintChanged: requestPaint()
    onPaint: {
        const painter = getContext("2d")
        painter.clearRect(0, 0, width, height)
        painter.beginPath()
        painter.moveTo(1, 6)
        painter.lineTo(4.5, 2)
        painter.lineTo(11, 2)
        painter.lineTo(11, 10)
        painter.lineTo(4.5, 10)
        painter.closePath()
        painter.fillStyle = tint
        painter.fill()
        painter.beginPath()
        painter.arc(5, 6, 1.15, 0, Math.PI * 2)
        painter.fillStyle = Theme.panel
        painter.fill()
    }
}
