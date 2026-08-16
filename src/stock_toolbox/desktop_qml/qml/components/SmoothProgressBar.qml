pragma ComponentBehavior: Bound
import QtQuick
import ".."

Item {
    id: bar
    property real progress: 0
    property color fillColor: Theme.accent
    readonly property real clampedProgress:
        Math.max(0, Math.min(1, progress))

    implicitHeight: 7
    clip: true

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.field
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: bar.fillColor
        transformOrigin: Item.Left
        scale: 1
        transform: Scale {
            origin.x: 0
            origin.y: bar.height / 2
            xScale: bar.clampedProgress

            Behavior on xScale {
                NumberAnimation {
                    duration: 220
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
}
