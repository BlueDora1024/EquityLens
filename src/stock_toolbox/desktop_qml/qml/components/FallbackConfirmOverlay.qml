import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: overlay

    property var gate: null
    signal settingsRequested()

    anchors.fill: parent
    visible: gate !== null && gate.pending
    z: 1100

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim

        MouseArea { anchors.fill: parent }
    }

    GlassPanel {
        anchors.centerIn: parent
        width: Math.min(560, overlay.width - 48)
        height: 370

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            Text {
                text: "行情服务暂时不可用"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
            }

            Text {
                Layout.fillWidth: true
                text: "当前供应商出现系统性故障。若改用 Yahoo，软件会丢弃本次临时结果，"
                    + "从第一步重新计算，并保证整条历史只使用一个行情来源。"
                color: Theme.secondaryText
                font.pixelSize: 12
                lineHeight: 1.4
                wrapMode: Text.Wrap
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 10

                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "分析工具"
                    value: overlay.gate ? overlay.gate.operation_label : ""
                }
                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "已完成"
                    value: overlay.gate
                        ? overlay.gate.completed_count + " / "
                            + overlay.gate.total_count : "0 / 0"
                }
                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "受影响"
                    value: overlay.gate
                        ? overlay.gate.failed_count + " 项" : "0 项"
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 64
                radius: 14
                color: Theme.field
                border.width: 1
                border.color: Theme.hairline

                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    text: (overlay.gate
                        ? overlay.gate.failure_text + " · "
                            + overlay.gate.interval_text + "。"
                        : "")
                        + "Yahoo 可能更慢，日内数据仅支持最近约 60 天；"
                        + "若网络不可达，可先前往高级设置检查代理。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    lineHeight: 1.35
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "结束运行"
                    onClicked: overlay.gate.decline()
                }
                GlassButton {
                    text: "前往网络设置"
                    onClicked: {
                        overlay.settingsRequested()
                        overlay.gate.open_network_settings()
                    }
                }
                GlassButton {
                    text: "使用 Yahoo 重新计算"
                    primary: true
                    onClicked: overlay.gate.accept()
                }
            }
        }
    }
}
