pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: view

    signal backRequested()

    property int selectedPeriodIndex: 0
    property bool reportDialogOpen: false
    readonly property int periodColumnWidth: 78
    readonly property int scoreColumnWidth: 64
    readonly property int levelColumnWidth: 136
    readonly property int buyDeviationColumnWidth: 94
    readonly property int sellDeviationColumnWidth: 94
    readonly property int statusColumnWidth: 70
    // qmllint disable unqualified
    readonly property string reportErrorText:
        extremeDeviationBridge.report_error
    // qmllint enable unqualified

    function percent(value): string {
        return value === null || value === undefined
            ? "—" : (Number(value) * 100).toFixed(1) + "%"
    }

    function scoreText(value): string {
        if (value === null || value === undefined) {
            return "—"
        }
        return Number(value) > 0 ? "+" + value : String(value)
    }

    function scoreColor(value): color {
        if (value === null || value === undefined || Number(value) === 0) {
            return Theme.secondaryText
        }
        return Number(value) < 0 ? Theme.success : Theme.danger
    }

    function deviationColor(value, buySide): color {
        if (value === null || value === undefined || Number(value) <= 0) {
            return Theme.faintText
        }
        return buySide ? Theme.success : Theme.danger
    }

    function periodExplanation(period): string {
        if (period.score === null || period.score === undefined) {
            return "该周期样本不足或数据异常，暂不计算评分。"
        }
        const score = Number(period.score)
        const evidence = "买入偏离 " + view.percent(period.buyDeviation)
            + "，卖出偏离 " + view.percent(period.sellDeviation) + "。"
        if (score <= -30) {
            return evidence + "买入侧综合强于卖出侧，原始评分 "
                + view.scoreText(score) + "，因此为“" + period.label
                + "”。负分表示偏买入，绝对值越大，偏离越明显。"
        }
        if (score >= 30) {
            return evidence + "卖出侧综合强于买入侧，原始评分 "
                + view.scoreText(score) + "，因此为“" + period.label
                + "”。正分表示偏卖出，绝对值越大，偏离越明显。"
        }
        return evidence + "两侧都未形成 30 分以上的单边观察信号，"
            + "原始评分 " + view.scoreText(score) + "，因此为“中性”。"
    }

    function displaySymbol(value): string {
        return String(value).replace(/\.US$/, "")
    }

    function identityTitle(detail): string {
        const symbol = view.displaySymbol(detail.symbol || "")
        const company = String(detail.companyName || "").trim()
        return company && company.toLowerCase() !== symbol.toLowerCase()
            ? company : symbol
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 11

        RowLayout {
            Layout.fillWidth: true
            GlassButton {
                text: "‹ 返回结果"
                onClicked: view.backRequested()
            }
            Column {
                spacing: 4
                Text {
                    // qmllint disable unqualified
                    text: view.identityTitle(
                        extremeDeviationBridge.selected_detail) || "选择证券"
                    // qmllint enable unqualified
                    color: Theme.text
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
                Text {
                    // qmllint disable unqualified
                    text: view.displaySymbol(
                        extremeDeviationBridge.selected_detail.symbol || "")
                        + " · "
                        + (extremeDeviationBridge.selected_detail.classification || "")
                    // qmllint enable unqualified
                    color: Theme.secondaryText
                    font.pixelSize: 10
                }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: summaryActions.implicitWidth + 16
                implicitHeight: 42
                radius: 14
                color: Theme.field
                RowLayout {
                    id: summaryActions
                    anchors.centerIn: parent
                    spacing: 8
                    GlassButton {
                        implicitHeight: 32
                        // qmllint disable unqualified
                        text: extremeDeviationBridge.report_running
                            ? "AI 解读中…"
                            : (extremeDeviationBridge.report_available
                                ? "查看 AI 解读" : "AI 解读")
                        enabled: (extremeDeviationBridge.ai_configured
                            || extremeDeviationBridge.report_available)
                            && Boolean(extremeDeviationBridge.selected_detail.symbol)
                            && !extremeDeviationBridge.report_running
                        onClicked: {
                            reportDialogOpen = true
                            if (!extremeDeviationBridge.report_available) {
                                extremeDeviationBridge.generate_selected_report()
                            }
                        }
                        // qmllint enable unqualified
                    }
                    Rectangle {
                        implicitWidth: conclusionLabel.implicitWidth + 20
                        implicitHeight: 30
                        radius: 15
                        color: Theme.accentSoft
                        Text {
                            id: conclusionLabel
                            anchors.centerIn: parent
                            // qmllint disable unqualified
                            text: (extremeDeviationBridge.selected_detail.consensusLabel || "—")
                                + " · "
                                + (extremeDeviationBridge.selected_detail.consensus
                                    === "PERIOD_DIVERGENCE"
                                    ? "关注 "
                                        + extremeDeviationBridge.selected_detail.attentionScore
                                    : view.scoreText(
                                        extremeDeviationBridge.selected_detail.score))
                            // qmllint enable unqualified
                            color: Theme.accent
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }

        GlassPanel {
            Layout.fillWidth: true
            // qmllint disable unqualified
            Layout.preferredHeight: Math.min(
                250, 58 + extremeDeviationBridge.period_details.length * 43)
            // qmllint enable unqualified

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 7

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "周期"
                        color: Theme.faintText
                        font.pixelSize: 9
                        Layout.preferredWidth: view.periodColumnWidth
                    }
                    Text { text: "评分"; color: Theme.faintText; font.pixelSize: 9; Layout.preferredWidth: view.scoreColumnWidth }
                    Text { text: "等级"; color: Theme.faintText; font.pixelSize: 9; Layout.preferredWidth: view.levelColumnWidth }
                    Text { text: "买入偏离"; color: Theme.faintText; font.pixelSize: 9; Layout.preferredWidth: view.buyDeviationColumnWidth }
                    Text { text: "卖出偏离"; color: Theme.faintText; font.pixelSize: 9; Layout.preferredWidth: view.sellDeviationColumnWidth }
                    Text { text: "状态"; color: Theme.faintText; font.pixelSize: 9; Layout.preferredWidth: view.statusColumnWidth }
                    Item { Layout.preferredWidth: 18 }
                    Item { Layout.fillWidth: true }
                }

                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 5
                    // qmllint disable unqualified
                    model: extremeDeviationBridge.period_details
                    // qmllint enable unqualified
                    delegate: Rectangle {
                        id: periodRow
                        required property var modelData
                        width: ListView.view.width
                        height: 38
                        radius: 10
                        color: Theme.field
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 8
                            Text {
                                text: periodRow.modelData.intervalLabel
                                color: Theme.text
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                Layout.preferredWidth: view.periodColumnWidth
                            }
                            Text {
                                text: view.scoreText(periodRow.modelData.score)
                                color: view.scoreColor(periodRow.modelData.score)
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                Layout.preferredWidth: view.scoreColumnWidth
                            }
                            Text {
                                text: periodRow.modelData.label
                                color: view.scoreColor(periodRow.modelData.score)
                                font.pixelSize: 10
                                font.weight: Font.Medium
                                Layout.preferredWidth: view.levelColumnWidth
                            }
                            Text {
                                text: view.percent(periodRow.modelData.buyDeviation)
                                color: view.deviationColor(
                                    periodRow.modelData.buyDeviation, true)
                                font.pixelSize: 10
                                font.weight: Font.Medium
                                Layout.preferredWidth: view.buyDeviationColumnWidth
                            }
                            Text {
                                text: view.percent(periodRow.modelData.sellDeviation)
                                color: view.deviationColor(
                                    periodRow.modelData.sellDeviation, false)
                                font.pixelSize: 10
                                font.weight: Font.Medium
                                Layout.preferredWidth: view.sellDeviationColumnWidth
                            }
                            Text {
                                text: periodRow.modelData.status
                                color: periodRow.modelData.status === "完成"
                                    ? Theme.success : Theme.warning
                                font.pixelSize: 10
                                Layout.preferredWidth: view.statusColumnWidth
                            }
                            InfoTip {
                                title: periodRow.modelData.intervalLabel
                                    + " · " + periodRow.modelData.label
                                tipText: view.periodExplanation(periodRow.modelData)
                                preferredWidth: 380
                                openLeft: true
                                openAbove: true
                                Layout.preferredWidth: 18
                                Layout.preferredHeight: 18
                            }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }

        GlassPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 300
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "历史偏离"; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    Repeater {
                        // qmllint disable unqualified
                        model: extremeDeviationBridge.period_details
                        // qmllint enable unqualified
                        ChoiceChip {
                            required property var modelData
                            required property int index
                            text: modelData.intervalLabel
                            checked: view.selectedPeriodIndex === index
                            onToggled: if (checked) view.selectedPeriodIndex = index
                        }
                    }
                }
                DeviationChart {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    // qmllint disable unqualified
                    points: extremeDeviationBridge.period_details.length
                        > view.selectedPeriodIndex
                        ? extremeDeviationBridge.period_details[view.selectedPeriodIndex].chartPoints : []
                    intervalLabel: extremeDeviationBridge.period_details.length
                        > view.selectedPeriodIndex
                        ? extremeDeviationBridge.period_details[view.selectedPeriodIndex].intervalLabel : ""
                    // qmllint enable unqualified
                }
            }
        }

    }

    RsAIReportOverlay {
        objectName: "extremeReportDialog"
        anchors.fill: parent
        visible: view.reportDialogOpen
        // qmllint disable unqualified
        reportText: extremeDeviationBridge.report_text
        errorText: view.reportErrorText
        running: extremeDeviationBridge.report_running
        // qmllint enable unqualified
        titleText: "AI 极值偏离解读"
        subtitleText: "基于当前单证券、本次运行冻结的已选周期结果"
        footerText: "AI 只解释冻结结果，不会修改偏离分数。"
        regenerateText: "重新分析"
        // qmllint disable unqualified
        regenerateEnabled: extremeDeviationBridge.ai_configured
        // qmllint enable unqualified
        onCloseRequested: view.reportDialogOpen = false
        onRegenerateRequested: {
            // qmllint disable unqualified
            extremeDeviationBridge.generate_selected_report()
            // qmllint enable unqualified
        }
    }
}
