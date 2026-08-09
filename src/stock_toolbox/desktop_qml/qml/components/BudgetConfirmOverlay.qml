import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: overlay
    objectName: "budgetConfirmOverlay"

    property int memberCount: 0
    property int dimensionCount: 0
    property int totalTasks: 0
    property int cacheHits: 0
    property int coldRequests: 0
    property string dataPath: ""
    property string quotaNotice: ""
    property string futuSerialNotice: ""
    property string dimensionLabel: "周期"
    property int quotaRemaining: -1
    property int quotaNewSymbols: -1
    property int quotaShortfall: 0
    readonly property bool quotaBlocked: quotaShortfall > 0

    signal confirmRequested()
    signal dismissRequested()
    signal yahooRequested()

    anchors.fill: parent
    z: 1000

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim

        MouseArea {
            anchors.fill: parent
        }
    }

    GlassPanel {
        anchors.centerIn: parent
        width: Math.min(520, overlay.width - 48)
        height: overlay.quotaBlocked || overlay.futuSerialNotice.length > 0 ? 350 : 310

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            Text {
                text: overlay.quotaBlocked
                    ? "富途历史额度不足"
                    : "确认本次资源消耗"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: overlay.quotaBlocked
                    ? "本次需要新增 " + overlay.quotaNewSymbols
                        + " 只证券，富途剩余 " + overlay.quotaRemaining
                        + "，缺少 " + overlay.quotaShortfall
                        + "。本次尚未开始计算。"
                    : overlay.futuSerialNotice.length > 0
                    ? overlay.futuSerialNotice
                        + "。选择 Yahoo 会从第一步开始整次计算，"
                        + "不会混用两家数据。"
                    : overlay.quotaNotice.length > 0
                    ? overlay.quotaNotice
                        + "。可返回缩小股票池；继续后若富途阻断，"
                        + "软件会询问是否改用 Yahoo 从第一步重新计算。"
                    : "预计冷请求超过默认保护线。软件不会修改股票池、周期或日期；"
                        + "确认后按最多四路并发执行，单项失败不会阻塞整批任务。"
                color: Theme.secondaryText
                font.pixelSize: 12
                lineHeight: 1.35
                wrapMode: Text.Wrap
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 10
                rowSpacing: 8

                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "证券 × " + overlay.dimensionLabel
                    value: overlay.memberCount + " × " + overlay.dimensionCount
                }
                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "缓存命中"
                    value: String(overlay.cacheHits)
                }
                GlassMetric {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    label: "预计外部请求"
                    value: String(overlay.coldRequests)
                }
            }

            Text {
                Layout.fillWidth: true
                text: "数据路径：" + overlay.dataPath
                    + " · 预计任务：" + overlay.totalTasks
                color: Theme.faintText
                font.pixelSize: 10
                elide: Text.ElideRight
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                GlassButton {
                    visible: overlay.quotaBlocked
                    text: "取消"
                    onClicked: overlay.dismissRequested()
                }
                GlassButton {
                    text: overlay.quotaBlocked ? "调整范围" : "返回调整"
                    onClicked: overlay.dismissRequested()
                }
                GlassButton {
                    visible: overlay.quotaBlocked || overlay.futuSerialNotice.length > 0
                    text: overlay.quotaBlocked ? "本次使用 Yahoo" : "改用 Yahoo"
                    primary: overlay.quotaBlocked
                    onClicked: overlay.yahooRequested()
                }
                GlassButton {
                    visible: !overlay.quotaBlocked
                    text: overlay.futuSerialNotice.length > 0
                        ? "继续使用富途" : "继续运行"
                    primary: true
                    onClicked: overlay.confirmRequested()
                }
            }
        }
    }
}
