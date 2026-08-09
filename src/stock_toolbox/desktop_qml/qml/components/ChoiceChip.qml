import QtQuick
import QtQuick.Controls
import ".."

CheckBox {
    id: control

    implicitHeight: Theme.controlHeight
    implicitWidth: leftPadding + label.implicitWidth + rightPadding
    spacing: 8
    leftPadding: 32
    rightPadding: 10

    indicator: Item {
        implicitWidth: 16
        implicitHeight: 16
        x: 8
        y: (control.height - height) / 2

        Rectangle {
            anchors.fill: parent
            radius: 6
            color: control.checked ? Theme.accent : Theme.field
            border.width: control.checked ? 0 : 1
            border.color: Theme.hairline
        }

        Text {
            anchors.centerIn: parent
            text: "✓"
            visible: control.checked
            color: "#FFFFFF"
            font.pixelSize: 10
            font.weight: Font.Bold
        }
    }

    contentItem: Text {
        id: label
        width: control.availableWidth
        height: control.availableHeight
        text: control.text
        color: control.checked ? Theme.accent : Theme.text
        font.pixelSize: 12
        font.weight: control.checked ? Font.DemiBold : Font.Normal
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 12
        color: control.checked ? Theme.accentSoft : Theme.field
        border.width: 1
        border.color: control.checked ? Theme.accent : Theme.hairline
    }
}
