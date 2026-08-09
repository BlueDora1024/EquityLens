pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import ".."

Rectangle {
    id: root
    objectName: "shellSidebar"

    radius: 19
    color: Theme.sidebar
    border.width: 1
    border.color: Theme.hairline

    Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 2

        Item {
            width: parent.width
            height: 58

            Rectangle {
                width: 32
                height: 32
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                radius: 11
                color: Theme.field
                border.width: 1
                border.color: Theme.hairline

                Text {
                    anchors.centerIn: parent
                    text: "⌁"
                    color: Theme.accent
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 44
                anchors.verticalCenter: parent.verticalCenter
                text: "EquityLens"
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
        }

        Repeater {
            // qmllint disable unqualified
            model: shellBridge.navigation
            // qmllint enable unqualified

            Loader {
                required property var modelData

                width: parent.width
                visible: modelData.visible
                height: visible ? implicitHeight : 0
                sourceComponent: modelData.kind === "heading"
                    ? headingComponent
                    : navigationComponent
                onLoaded: item.rowData = modelData
            }
        }
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.bottom: settingsButton.top
        anchors.bottomMargin: 12
        text: "本机数据 · 私有"
        color: Theme.faintText
        font.pixelSize: 10
    }

    GlassButton {
        id: settingsButton
        objectName: "settingsButton"
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 18
        implicitWidth: 36
        implicitHeight: 36
        text: "⚙"
        Accessible.name: "设置"
        ToolTip.text: "设置"
        ToolTip.visible: hovered
        onClicked: {
            // qmllint disable unqualified
            shellBridge.open_settings()
            // qmllint enable unqualified
        }
    }

    Component {
        id: headingComponent

        Text {
            property var rowData: ({})

            text: rowData.label
            color: Theme.faintText
            font.pixelSize: 10
            font.weight: Font.Medium
            topPadding: rowData.label === "全局数据" ? 8 : 10
            bottomPadding: 6
        }
    }

    Component {
        id: navigationComponent

        SidebarItem {
            property var rowData: ({})

            objectName: rowData.kind === "tool"
                && rowData.analysisId === "rs_strength"
                ? "sidebarRsItem" : ""
            width: root.width - 28
            glyph: rowData.glyph
            text: rowData.label
            helpText: rowData.helpText || ""
            selected: rowData.selected
            subordinate: rowData.kind === "subitem"
            onClicked: {
                if (rowData.pageId) {
                    // qmllint disable unqualified
                    if (rowData.pageId === "extreme_deviation.run") {
                        extremeDeviationBridge.prepare_new_run()
                    }
                    shellBridge.navigate(rowData.pageId)
                    // qmllint enable unqualified
                }
            }
        }
    }
}
