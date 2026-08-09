import QtQuick
import QtQuick.Layouts
import ".."

GlassPanel {
    id: card

    property bool loading: false
    property int memberCount: 0
    property int dimensionCount: 0
    property int totalTasks: 0
    property int cacheHits: 0
    property int coldRequests: 0
    property string dataPath: "等待资源预检"
    property string quotaNotice: ""
    property string dimensionLabel: "周期"

    implicitHeight: 58

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        spacing: 14

        BusySpinner {
            Layout.preferredWidth: 18
            Layout.preferredHeight: 18
            running: card.loading
            visible: running
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Text {
                text: card.loading ? "正在核算资源…" : "本次资源"
                color: Theme.text
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: "数据路径：" + card.dataPath + " · 最多四路并发"
                    + (card.quotaNotice.length > 0
                        ? " · " + card.quotaNotice : "")
                color: Theme.secondaryText
                font.pixelSize: 9
                elide: Text.ElideRight
            }
        }

        Repeater {
            model: [
                {"label": "证券", "value": card.memberCount},
                {"label": card.dimensionLabel, "value": card.dimensionCount},
                {"label": "预计任务", "value": card.totalTasks},
                {"label": "缓存命中", "value": card.cacheHits},
                {"label": "预计外部请求", "value": card.coldRequests}
            ]

            ColumnLayout {
                required property var modelData
                Layout.preferredWidth: 66
                spacing: 1

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: parent.modelData.label
                    color: Theme.faintText
                    font.pixelSize: 9
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: String(parent.modelData.value)
                    color: parent.modelData.label === "预计外部请求"
                        && parent.modelData.value > 50
                        ? Theme.danger : Theme.text
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }
    }
}
