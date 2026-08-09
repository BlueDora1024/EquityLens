pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import ".."

Item {
    id: root

    property string title: ""
    property string tipText: ""
    property int preferredWidth: 310
    property bool openLeft: false
    property bool openAbove: false
    property bool lightSurface: false
    property bool showIndicator: true

    implicitWidth: 18
    implicitHeight: 18
    visible: tipText.length > 0

    Rectangle {
        visible: root.showIndicator
        anchors.centerIn: parent
        width: 16
        height: 16
        radius: 8
        color: tipMouse.containsMouse ? Theme.accentSoft : Theme.field
        border.width: 1
        border.color: tipMouse.containsMouse ? Theme.accent : Theme.hairline

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -0.5
            text: "?"
            color: tipMouse.containsMouse
                ? Theme.accent : Theme.secondaryText
            font.pixelSize: 10
            font.weight: Font.DemiBold
        }
    }

    MouseArea {
        id: tipMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.WhatsThisCursor
    }

    ToolTip {
        id: tipPopup
        visible: tipMouse.containsMouse
        delay: 180
        timeout: 12000
        x: root.openLeft ? root.width - width : 0
        y: root.openAbove ? -height - 8 : root.height + 8
        padding: 13
        implicitWidth: root.preferredWidth

        contentItem: Column {
            spacing: root.title ? 6 : 0

            Text {
                visible: Boolean(root.title)
                width: parent.width
                text: root.title
                color: root.lightSurface ? "#182230" : Theme.text
                font.pixelSize: 11
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: root.tipText
                color: root.lightSurface ? "#667085" : Theme.secondaryText
                font.pixelSize: 10
                lineHeight: 1.35
                wrapMode: Text.Wrap
            }
        }

        background: Rectangle {
            radius: 13
            color: root.lightSurface
                ? "#FFFDFCF9"
                : (Theme.dark ? "#F22A2E35" : "#FCF9F8F5")
            border.width: 1
            border.color: root.lightSurface ? "#FFD7DBE2" : Theme.hairline
        }
    }
}
