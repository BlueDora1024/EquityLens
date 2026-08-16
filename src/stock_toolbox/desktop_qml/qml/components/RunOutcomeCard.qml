pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import ".."

Item {
    id: card

    property bool running: false
    property bool recoveryVisible: false
    property string recoveryTone: "neutral"
    property string recoveryMessage: ""
    property int retryCount: 0
    property real waitSeconds: 0
    property int activeConcurrency: 4
    property bool outcomeVisible: false
    property string outcomeTone: "neutral"
    property string outcomeTitle: ""
    property string outcomeSummary: ""
    property string runningTitle: ""
    property string runningReason: ""
    property real progress: 0
    property string primaryAction: ""
    property string primaryLabel: ""
    property int failureCount: 0

    signal primaryActionRequested(string action)
    signal detailsRequested()

    readonly property bool present:
        running || recoveryVisible || outcomeVisible
    readonly property bool terminal: outcomeVisible && !running
    readonly property string tone: terminal
        ? outcomeTone : (recoveryVisible ? recoveryTone : "neutral")
    readonly property bool supportedAction: primaryAction === "retry"
        || primaryAction === "open_settings"
    readonly property bool hasPrimaryAction: terminal && supportedAction
        && primaryLabel.length > 0
    readonly property bool hasFailureEvidence: failureCount > 0
    readonly property bool hasMeta: !terminal
        && (retryCount > 0 || waitSeconds > 0 || activeConcurrency === 1)
    readonly property bool hasActions:
        hasPrimaryAction || hasFailureEvidence
    readonly property bool stackActions: hasActions && width < 420
    readonly property string titleText: terminal
        ? outcomeTitle : runningTitle
    readonly property string reasonText: terminal
        ? outcomeSummary
        : (recoveryVisible ? recoveryMessage : runningReason)
    readonly property color toneColor: {
        if (tone === "warning") {
            return Theme.warning
        }
        if (tone === "success") {
            return Theme.success
        }
        if (tone === "danger") {
            return Theme.danger
        }
        return Theme.accent
    }
    readonly property color toneSurface: {
        if (tone === "warning") {
            return Theme.warningSoft
        }
        if (tone === "success") {
            return Theme.successSoft
        }
        if (tone === "danger") {
            return Theme.dangerSoft
        }
        return Theme.accentSoft
    }

    visible: present
    opacity: present ? 1 : 0
    implicitHeight: present ? contentGrid.implicitHeight + 24 : 0

    Behavior on opacity {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: 16
        color: card.toneSurface
        border.width: 1
        border.color: Theme.hairline

        Behavior on color {
            ColorAnimation { duration: 170 }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 1
            anchors.topMargin: 10
            anchors.bottomMargin: 10
            width: 3
            radius: 2
            color: card.toneColor

            Behavior on color {
                ColorAnimation { duration: 170 }
            }
        }

        GridLayout {
            id: contentGrid
            anchors.fill: parent
            anchors.leftMargin: 15
            anchors.rightMargin: 13
            anchors.topMargin: 12
            anchors.bottomMargin: 12
            columns: card.stackActions ? 2 : 3
            rowSpacing: 8
            columnSpacing: 12

            Rectangle {
                Layout.row: 0
                Layout.column: 0
                Layout.preferredWidth: 8
                Layout.preferredHeight: 8
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 6
                radius: 4
                color: card.toneColor
            }

            ColumnLayout {
                Layout.row: 0
                Layout.column: 1
                Layout.fillWidth: true
                spacing: 4

                Text {
                    objectName: "outcomeTitleText"
                    Layout.fillWidth: true
                    text: card.titleText
                    color: Theme.text
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                }

                Text {
                    objectName: "outcomeSummaryText"
                    Layout.fillWidth: true
                    text: card.reasonText
                    color: Theme.secondaryText
                    font.pixelSize: 10
                    maximumLineCount: card.stackActions ? 2 : 1
                    wrapMode: card.stackActions ? Text.Wrap : Text.NoWrap
                    elide: card.stackActions
                        ? Text.ElideNone : Text.ElideRight
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                }

                RowLayout {
                    visible: card.hasMeta
                    Layout.fillWidth: true
                    spacing: 12

                    Text {
                        visible: card.retryCount > 0
                        text: "重试 " + card.retryCount + " 次"
                        color: card.toneColor
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                    }
                    Text {
                        visible: card.waitSeconds > 0
                        text: "约 " + Math.ceil(card.waitSeconds) + " 秒后继续"
                        color: Theme.secondaryText
                        font.pixelSize: 9
                    }
                    Text {
                        visible: card.activeConcurrency === 1
                        text: "已降为 1 路请求"
                        color: Theme.warning
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            RowLayout {
                objectName: "outcomeActionRow"
                visible: card.hasActions
                Layout.row: card.stackActions ? 1 : 0
                Layout.column: card.stackActions ? 1 : 2
                Layout.alignment: Qt.AlignVCenter
                spacing: 7

                GlassButton {
                    objectName: "outcomeDetailsButton"
                    visible: card.hasFailureEvidence
                    text: "查看详情"
                    Accessible.name: text
                    onClicked: card.detailsRequested()
                }

                GlassButton {
                    objectName: "outcomePrimaryButton"
                    visible: card.hasPrimaryAction
                    text: card.primaryLabel
                    primary: true
                    Accessible.name: text
                    onClicked:
                        card.primaryActionRequested(card.primaryAction)
                }
            }
        }

        Rectangle {
            visible: card.running
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 3
            color: "transparent"
            clip: true

            Rectangle {
                anchors.fill: parent
                radius: 2
                color: card.toneColor
                transformOrigin: Item.Left
                transform: Scale {
                    origin.x: 0
                    origin.y: 1.5
                    xScale: Math.max(0, Math.min(1, card.progress))

                    Behavior on xScale {
                        NumberAnimation {
                            duration: 220
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }
        }
    }
}
