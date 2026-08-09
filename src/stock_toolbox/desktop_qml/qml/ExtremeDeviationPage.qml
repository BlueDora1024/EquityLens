import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: page
    objectName: "extremeDeviationPage"
    signal networkSettingsRequested()

    // qmllint disable unqualified
    readonly property bool resultsMode:
        shellBridge.current_page === "extreme_deviation.results"
    // qmllint enable unqualified
    property bool detailOpen: false
    readonly property bool modalOverlayOpen:
        extremeRunView.visible && extremeRunView.modalOverlayOpen

    function openDetail(runId): void {
        // qmllint disable unqualified
        if (extremeDeviationBridge.select_run(runId)) {
            detailOpen = true
            shellBridge.navigate("extreme_deviation.results")
        }
        // qmllint enable unqualified
    }

    function showResults(): void {
        detailOpen = false
        // qmllint disable unqualified
        shellBridge.navigate("extreme_deviation.results")
        // qmllint enable unqualified
    }

    Timer {
        id: completionTransition
        interval: 520
        repeat: false
        onTriggered: page.showResults()
    }

    onResultsModeChanged: {
        if (!resultsMode) {
            detailOpen = false
            // qmllint disable unqualified
            extremeDeviationBridge.prepare_new_run()
            // qmllint enable unqualified
        }
    }
    onVisibleChanged: {
        if (visible && !resultsMode) {
            // qmllint disable unqualified
            extremeDeviationBridge.prepare_new_run()
            // qmllint enable unqualified
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 64

            Column {
                spacing: 6
                Text {
                    text: page.detailOpen ? "极值偏离结论" : "极值偏离"
                    color: Theme.text
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    text: page.resultsMode
                        ? "每次单证券复盘均会保存一条结果记录。"
                        : "收盘后按所选周期复盘，识别买卖压力的程度与共振。"
                    color: Theme.secondaryText
                    font.pixelSize: 12
                }
            }
            Item { Layout.fillWidth: true }
        }

        GlassPanel {
            visible: !page.resultsMode
            Layout.fillWidth: true
            Layout.preferredHeight: 62

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                spacing: 12
                Text {
                    text: "怎么阅读"
                    color: Theme.accent
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: "负分偏买入观察，正分偏卖出观察，绝对值越大表示偏离程度越明显；"
                        + "短周期更灵敏，日线和周线更稳定。多个周期同向时关注共振，"
                        + "方向相反时优先复盘周期分歧。本工具只用于收盘后复盘。"
                    color: Theme.secondaryText
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
            }
        }

        ExtremeRunView {
            id: extremeRunView
            visible: !page.resultsMode
            Layout.fillWidth: true
            Layout.fillHeight: true
            onNetworkSettingsRequested: page.networkSettingsRequested()
        }

        ExtremeResultsView {
            visible: page.resultsMode && !page.detailOpen
            Layout.fillWidth: true
            Layout.fillHeight: true
            onDetailRequested: runId => page.openDetail(runId)
        }

        ExtremeDetailView {
            visible: page.resultsMode && page.detailOpen
            Layout.fillWidth: true
            Layout.fillHeight: true
            onBackRequested: page.detailOpen = false
        }
    }

    Connections {
        // qmllint disable unqualified
        target: extremeDeviationBridge
        // qmllint enable unqualified
        function onFinished(): void {
            // qmllint disable unqualified
            if (extremeDeviationBridge.terminal_has_usable_results) {
            // qmllint enable unqualified
                completionTransition.restart()
                return
            }
            page.detailOpen = false
            // qmllint disable unqualified
            shellBridge.navigate("extreme_deviation.run")
            // qmllint enable unqualified
        }
    }
}
