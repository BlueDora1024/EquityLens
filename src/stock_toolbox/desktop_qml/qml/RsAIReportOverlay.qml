pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
import "components"

Item {
    id: root
    objectName: "rsAIReportOverlay"
    z: 70
    focus: visible

    property string reportText: ""
    property string titleText: "AI 强弱解读"
    property string subtitleText: "基于本次冻结的分类与个股 RS 结果"
    property string footerText: "AI 只解释冻结结果，不会修改 RS 分数。"
    property string regenerateText: "重新生成"
    property bool regenerateEnabled: true
    property string errorText: ""
    property bool running: false

    signal closeRequested
    signal regenerateRequested

    onVisibleChanged: {
        if (visible) {
            forceActiveFocus()
        }
    }
    Keys.onEscapePressed: root.closeRequested()

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }
    }

    GlassPanel {
        id: reportPanel
        objectName: "rsAIReportPanel"
        width: Math.min(
            parent.width - 36,
            Math.min(900, Math.max(620, parent.width * 0.7)))
        height: Math.min(
            parent.height - 36,
            Math.max(360, Math.min(620, parent.height * 0.7)))
        anchors.centerIn: parent
        color: Theme.dark ? "#F021242A" : "#FFF8F7F4"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: root.titleText
                        color: Theme.text
                        font.pixelSize: 20
                        font.weight: Font.Bold
                    }
                    Text {
                        text: root.subtitleText
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                }
                BusySpinner {
                    visible: root.running
                    running: visible
                }
                Text {
                    visible: root.running
                    text: "正在重新生成…"
                    color: Theme.accent
                    font.pixelSize: 10
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 15
                color: Theme.field
                border.width: 1
                border.color: Theme.hairline

                Flickable {
                    anchors.fill: parent
                    anchors.margins: 16
                    clip: true
                    contentWidth: width
                    contentHeight: reportBody.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    Text {
                        id: reportBody
                        objectName: "rsAIReportBody"
                        width: parent.width
                        text: root.reportText
                        textFormat: Text.PlainText
                        color: Theme.text
                        font.pixelSize: 12
                        lineHeight: 1.45
                        wrapMode: Text.Wrap
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.errorText.length > 0
                text: root.errorText
                color: Theme.danger
                font.pixelSize: 10
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.footerText
                    color: Theme.faintText
                    font.pixelSize: 9
                }
                GlassButton {
                    text: root.regenerateText
                    enabled: !root.running && root.regenerateEnabled
                    onClicked: root.regenerateRequested()
                }
                GlassButton {
                    id: closeButton
                    objectName: "rsAIReportCloseButton"
                    text: "关闭"
                    primary: true
                    onClicked: root.closeRequested()
                }
            }
        }
    }
}
