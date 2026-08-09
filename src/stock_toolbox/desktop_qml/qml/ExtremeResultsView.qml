pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

Item {
    id: view

    signal detailRequested(string runId)

    function displaySymbol(value): string {
        return String(value).replace(/\.US$/, "")
    }

    function securityTitle(symbol, companyName): string {
        const code = view.displaySymbol(symbol)
        const name = String(companyName || "").trim()
        return !name || name.toUpperCase() === code.toUpperCase()
            ? code : code + " · " + name
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "结果记录"
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Text {
                text: "最近十次 · 以设置时区显示"
                color: Theme.faintText
                font.pixelSize: 10
            }
            Item { Layout.fillWidth: true }
        }

        GlassPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: resultHistory
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                spacing: 7
                // qmllint disable unqualified
                model: extremeDeviationBridge.result_history
                // qmllint enable unqualified

                delegate: Rectangle {
                    id: historyRow
                    required property var modelData
                    width: ListView.view.width
                    height: 66
                    radius: 13
                    color: historyMouse.containsMouse
                        ? Theme.accentSoft : Theme.field
                    border.width: 1
                    border.color: Theme.hairline

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 10
                        spacing: 12

                        Text {
                            text: historyRow.modelData.completedAt
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            Layout.preferredWidth: 124
                        }
                        Column {
                            Layout.preferredWidth: 190
                            spacing: 3
                            Text {
                                text: view.securityTitle(
                                    historyRow.modelData.symbol,
                                    historyRow.modelData.companyName)
                                color: Theme.text
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                width: parent.width
                                elide: Text.ElideRight
                            }
                            Text {
                                text: historyRow.modelData.summary
                                color: Theme.secondaryText
                                font.pixelSize: 10
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            implicitWidth: statusText.implicitWidth + 18
                            implicitHeight: 26
                            radius: 13
                            color: historyRow.modelData.status === "完成"
                                ? Theme.successSoft : Theme.warningSoft
                            Text {
                                id: statusText
                                anchors.centerIn: parent
                                text: historyRow.modelData.status
                                color: historyRow.modelData.status === "完成"
                                    ? Theme.success : Theme.warning
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }
                        GlassButton {
                            text: "查看结论"
                            implicitWidth: 92
                            onClicked: view.detailRequested(
                                historyRow.modelData.runId)
                        }
                    }

                    MouseArea {
                        id: historyMouse
                        anchors.fill: parent
                        anchors.rightMargin: 112
                        hoverEnabled: true
                        onClicked: view.detailRequested(historyRow.modelData.runId)
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: resultHistory.count === 0
                    text: "完成一次单证券复盘后，结果会保存在这里。"
                    color: Theme.faintText
                    font.pixelSize: 11
                }
            }
        }
    }
}
