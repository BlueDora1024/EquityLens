pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

FocusScope {
    id: overlay
    objectName: "updateOverlay"
    z: 1900
    visible: false
    opacity: visible ? 1 : 0
    Accessible.role: Accessible.Dialog
    Accessible.name: "EquityLens 软件更新"
    // qmllint disable unqualified
    property var bridge: updateBridge
    // qmllint enable unqualified

    Behavior on opacity {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim
        MouseArea { anchors.fill: parent }
    }

    GlassPanel {
        anchors.centerIn: parent
        width: Math.min(540, overlay.width - 48)
        height: Math.min(440, overlay.height - 56)
        color: Theme.overlayPanel

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                Rectangle {
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 36
                    radius: 12
                    color: Theme.accentSoft
                    Text {
                        anchors.centerIn: parent
                        text: "↥"
                        color: Theme.accent
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: "EquityLens 有新版本"
                        color: Theme.text
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: overlay.bridge.latest_tag + " · 适用于 "
                            + overlay.bridge.architecture
                        color: Theme.secondaryText
                        font.pixelSize: 11
                    }
                }
            }

            Text {
                text: "本次更新"
                color: Theme.text
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: overlay.bridge.release_notes
                    RowLayout {
                        id: releaseNoteRow
                        required property string modelData
                        Layout.fillWidth: true
                        spacing: 9
                        Rectangle {
                            Layout.preferredWidth: 6
                            Layout.preferredHeight: 6
                            radius: 3
                            color: Theme.accent
                        }
                        Text {
                            Layout.fillWidth: true
                            text: releaseNoteRow.modelData
                            color: Theme.secondaryText
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                Text {
                    visible: overlay.bridge.release_notes.length === 0
                    text: "此版本包含稳定性与使用体验改进。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 52
                radius: 14
                color: Theme.field
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    Text { text: "✓"; color: Theme.success; font.pixelSize: 12 }
                    Text {
                        Layout.fillWidth: true
                        text: "本地证券、配置和历史记录不会被修改"
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                }
            }

            RowLayout {
                visible: overlay.bridge.busy || overlay.bridge.status === "restarting"
                Layout.fillWidth: true
                BusySpinner { running: true }
                Text {
                    Layout.fillWidth: true
                    text: overlay.bridge.message
                    color: Theme.secondaryText
                    font.pixelSize: 10
                }
                Text {
                    visible: overlay.bridge.progress > 0
                    text: overlay.bridge.progress + "%"
                    color: Theme.accent
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "稍后"
                    enabled: !overlay.bridge.busy
                    onClicked: overlay.bridge.dismiss_prompt()
                }
                GlassButton {
                    objectName: "installUpdateButton"
                    text: overlay.bridge.busy ? "正在准备更新…" : "下载并更新"
                    primary: true
                    busy: overlay.bridge.busy
                    enabled: !overlay.bridge.busy
                    onClicked: overlay.bridge.install_update()
                }
            }
        }
    }
}
