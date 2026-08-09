import QtQuick
import QtQuick.Controls
import ".."

Button {
    id: control

    property string glyph: ""
    property string helpText: ""
    property bool selected: false
    property bool subordinate: false

    implicitHeight: subordinate ? 34 : 38
    hoverEnabled: true
    leftPadding: subordinate ? 36 : 12
    rightPadding: 10

    contentItem: Row {
        width: control.availableWidth
        height: control.availableHeight
        spacing: 9

        Text {
            visible: !control.subordinate
            width: 16
            height: parent.height
            text: control.glyph
            color: control.selected ? Theme.accent : Theme.secondaryText
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        Text {
            height: parent.height
            text: control.text
            color: control.selected ? Theme.accent : Theme.text
            font.pixelSize: 13
            font.weight: control.selected ? Font.DemiBold : Font.Normal
            verticalAlignment: Text.AlignVCenter
        }

        InfoTip {
            objectName: control.helpText ? "sidebarRsHelp" : ""
            anchors.verticalCenter: parent.verticalCenter
            title: "RS 强度"
            tipText: control.helpText
            preferredWidth: 292
        }
    }

    background: Rectangle {
        radius: 12
        color: control.selected
            ? Theme.accentSoft
            : (control.hovered ? Theme.field : "transparent")
    }
}
