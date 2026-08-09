import QtQuick
import QtQuick.Controls
import ".."

Button {
    id: control

    property bool primary: false
    property bool busy: false
    property color busyColor: primary ? "#FFFFFF" : Theme.accent

    implicitHeight: Theme.controlHeight
    implicitWidth: Math.max(
        72,
        label.implicitWidth + 30 + (busy ? 22 : 0))
    hoverEnabled: true
    transformOrigin: Item.Center
    scale: control.down ? 0.97 : 1

    Behavior on scale {
        NumberAnimation {
            duration: 120
            easing.type: Easing.OutCubic
        }
    }

    contentItem: Item {
        width: control.availableWidth
        height: control.availableHeight

        Row {
            anchors.centerIn: parent
            spacing: 7

            BusySpinner {
                width: 15
                height: 15
                anchors.verticalCenter: parent.verticalCenter
                visible: control.busy
                running: visible
                indicatorColor: control.busyColor
            }

            Text {
                id: label
                height: control.availableHeight
                text: control.text
                color: control.primary ? "#FFFFFF" : Theme.text
                font.pixelSize: 13
                font.weight: Font.Medium
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    background: Rectangle {
        radius: 12
        color: control.primary
            ? Theme.accent
            : (control.hovered ? Theme.accentSoft : Theme.field)
        border.width: control.primary ? 0 : 1
        border.color: Theme.hairline
        opacity: control.enabled ? 1 : 0.42

        Behavior on color {
            ColorAnimation { duration: 120 }
        }
    }
}
