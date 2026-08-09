import QtQuick
import QtQuick.Controls
import ".."

BusyIndicator {
    id: spinner

    property color indicatorColor: Theme.accent

    implicitWidth: 18
    implicitHeight: 18
    padding: 2

    contentItem: Item {
        id: wheel
        implicitWidth: 14
        implicitHeight: 14

        Rectangle {
            width: 4
            height: 4
            radius: 2
            anchors.horizontalCenter: parent.horizontalCenter
            y: 0
            color: spinner.indicatorColor
        }
        Rectangle {
            width: 4
            height: 4
            radius: 2
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            color: spinner.indicatorColor
            opacity: 0.72
        }
        Rectangle {
            width: 4
            height: 4
            radius: 2
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            color: spinner.indicatorColor
            opacity: 0.44
        }
        RotationAnimator {
            target: wheel
            from: 0
            to: 360
            duration: 850
            loops: Animation.Infinite
            running: spinner.running && spinner.visible
        }
    }
}
