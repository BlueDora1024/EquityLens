pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
import "components"

Rectangle {
    id: overlay
    objectName: "scenarioLabOverlay"
    z: 50

    signal closeRequested
    property string selectedScenarioId: ""

    opacity: visible ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    color: Theme.modalScrim
    MouseArea { anchors.fill: parent }

    GlassPanel {
        width: Math.min(850, overlay.width - 80)
        height: Math.min(590, overlay.height - 70)
        anchors.centerIn: parent
        color: Theme.dark ? "#F021242A" : "#FAF5F4F1"
        scale: overlay.visible ? 1 : 0.985
        Behavior on scale {
            NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Column {
                    spacing: 5
                    Text {
                        text: "Scenario Lab"
                        color: Theme.text
                        font.pixelSize: 22
                        font.weight: Font.Bold
                    }
                    Text {
                        // qmllint disable unqualified
                        text: scenarioBridge.isolation_note
                        // qmllint enable unqualified
                        color: Theme.secondaryText
                        font.pixelSize: 10
                    }
                }
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "完成"
                    onClicked: overlay.closeRequested()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                GlassPanel {
                    Layout.preferredWidth: 310
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 8
                        Text {
                            text: "确定性测试剧本"
                            color: Theme.text
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 6
                            // qmllint disable unqualified
                            model: scenarioBridge.scenarios
                            // qmllint enable unqualified
                            delegate: Rectangle {
                                id: scenarioRow
                                required property var modelData
                                width: ListView.view.width
                                height: 58
                                radius: 12
                                color: overlay.selectedScenarioId
                                    === scenarioRow.modelData.id
                                    ? Theme.accentSoft : Theme.field
                                border.width: 1
                                border.color: Theme.hairline
                                Column {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 11
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 3
                                    Text {
                                        text: scenarioRow.modelData.title
                                        color: Theme.text
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: scenarioRow.modelData.id
                                        color: Theme.faintText
                                        font.pixelSize: 8
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: overlay.selectedScenarioId =
                                        scenarioRow.modelData.id
                                }
                            }
                        }
                    }
                }

                GlassPanel {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: 9
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "隔离运行结果"
                                color: Theme.text
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            GlassButton {
                                // qmllint disable unqualified
                                text: scenarioBridge.running
                                    ? "运行中…" : "运行所选场景"
                                enabled: overlay.selectedScenarioId.length > 0
                                    && !scenarioBridge.running
                                onClicked: scenarioBridge.run_scenario(
                                    overlay.selectedScenarioId)
                                // qmllint enable unqualified
                                primary: true
                            }
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            TextArea {
                                readOnly: true
                                // qmllint disable unqualified
                                text: scenarioBridge.running
                                    ? "运行中…"
                                    : (scenarioBridge.result_text
                                        || "选择剧本后运行，结果会显示在这里。")
                                // qmllint enable unqualified
                                color: Theme.secondaryText
                                font.family: "Menlo"
                                font.pixelSize: 10
                                wrapMode: TextEdit.Wrap
                                background: Rectangle {
                                    radius: Theme.controlRadius
                                    color: Theme.field
                                    border.width: 1
                                    border.color: Theme.hairline
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: {
        // qmllint disable unqualified
        if (scenarioBridge.scenarios.length > 0) {
            overlay.selectedScenarioId = scenarioBridge.scenarios[0].id
        }
        // qmllint enable unqualified
    }
}
