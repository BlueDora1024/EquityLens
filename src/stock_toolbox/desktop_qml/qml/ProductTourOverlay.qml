pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "."
import "components"

FocusScope {
    id: overlay
    objectName: "productTourOverlay"

    signal closeRequested()
    signal dismissForeverRequested()

    property int currentSlide: 0
    property int focusRevision: 0
    readonly property var slides: [
        {
            "title": "先建立全局证券库",
            "body": "证券只维护一份。导入并补齐基础资料后，可以在多个股票池里重复使用。",
            "section": "全局证券"
        },
        {
            "title": "用标签与股票池组织计算",
            "body": "标签负责分类，股票池负责本次计算范围；同一只证券不会因此产生重复资料。",
            "section": "全局标签 · 股票池"
        },
        {
            "title": "选择一个分析工具运行",
            "body": "RS、拐点筛选和极值偏离各自独立运行、独立保存结果，按复盘目的选择即可。",
            "section": "分析工具"
        },
        {
            "title": "在结果里复盘，不追逐预测",
            "body": "结合周期、评分和信号时间看证据；AI 解读只负责整理已有结果，不替代判断。",
            "section": "结果与历史"
        },
        {
            "title": "网络异常从设置恢复",
            "body": "在设置里检查当前供应商、代理和 Yahoo 备用行情。失败时软件会说明原因并引导到这里。",
            "section": "设置 · 网络"
        }
    ]
    readonly property var slide: slides[currentSlide]
    readonly property Item focusTarget: [
        securitiesTarget,
        organizationTarget,
        analysesTarget,
        resultsTarget,
        settingsTarget
    ][currentSlide]

    function closeTour(): void {
        if (dismissChoice.checked) {
            overlay.dismissForeverRequested()
        }
        overlay.closeRequested()
    }

    anchors.fill: parent
    z: 2300
    opacity: visible ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }
    activeFocusOnTab: true
    Accessible.role: Accessible.Dialog
    Accessible.name: "使用引导"

    onVisibleChanged: {
        if (visible) {
            currentSlide = 0
            dismissChoice.checked = false
            Qt.callLater(() => {
                focusRevision += 1
                nextButton.forceActiveFocus()
            })
        }
    }
    onCurrentSlideChanged: Qt.callLater(() => focusRevision += 1)
    Keys.onEscapePressed: closeTour()
    Keys.onLeftPressed: currentSlide = Math.max(0, currentSlide - 1)
    Keys.onRightPressed: {
        if (currentSlide < slides.length - 1) {
            currentSlide += 1
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.modalScrim

        MouseArea {
            anchors.fill: parent
        }
    }

    Rectangle {
        id: card
        objectName: "productTourCard"
        anchors.centerIn: parent
        width: Math.min(880, overlay.width - 40)
        height: Math.min(690, overlay.height - 24)
        radius: 24
        color: Theme.overlayPanel
        border.width: 1
        border.color: Theme.hairline
        scale: overlay.visible ? 1 : 0.985
        Behavior on scale {
            NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5

                    Text {
                        Layout.fillWidth: true
                        text: overlay.slide.title
                        color: Theme.text
                        font.pixelSize: 23
                        font.weight: Font.DemiBold
                    }

                    Text {
                        Layout.fillWidth: true
                        text: overlay.slide.body
                        color: Theme.secondaryText
                        font.pixelSize: 12
                        lineHeight: 1.35
                        wrapMode: Text.Wrap
                    }
                }

                GlassButton {
                    text: "关闭"
                    Accessible.name: "关闭使用引导"
                    onClicked: overlay.closeTour()
                }
            }

            Rectangle {
                id: illustration
                objectName: "productTourIllustration"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 420
                radius: 18
                color: Theme.dark ? "#171B21" : "#F2F1EE"
                border.width: 1
                border.color: Theme.hairline
                clip: true
                onWidthChanged: Qt.callLater(() => overlay.focusRevision += 1)
                onHeightChanged: Qt.callLater(() => overlay.focusRevision += 1)

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 34
                    color: Theme.dark ? "#20242B" : "#E7E6E2"

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 6
                        Repeater {
                            model: ["#FF5F57", "#FEBC2E", "#28C840"]
                            Rectangle {
                                required property color modelData
                                width: 8
                                height: 8
                                radius: 4
                                color: modelData
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: "EquityLens"
                        color: Theme.faintText
                        font.pixelSize: 9
                    }
                }

                Rectangle {
                    x: 12
                    y: 46
                    width: parent.width * 0.26
                    height: parent.height - 58
                    radius: 15
                    color: Theme.sidebar

                    Text {
                        id: sidebarTitle
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.top: parent.top
                        anchors.topMargin: 12
                        text: "EquityLens"
                        color: Theme.text
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }

                    Rectangle {
                        id: securitiesTarget
                        objectName: "productTourTargetSecurities"
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        anchors.top: sidebarTitle.bottom
                        anchors.topMargin: 12
                        height: 29
                        radius: 9
                        color: Theme.field
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "#  全局证券"
                            color: Theme.secondaryText
                            font.pixelSize: 9
                        }
                    }

                    Column {
                        id: organizationTarget
                        objectName: "productTourTargetOrganization"
                        anchors.left: securitiesTarget.left
                        anchors.right: securitiesTarget.right
                        anchors.top: securitiesTarget.bottom
                        anchors.topMargin: 7
                        spacing: 7
                        Repeater {
                            model: ["◇  全局标签", "▱  股票池"]
                            Rectangle {
                                required property string modelData
                                width: organizationTarget.width
                                height: 29
                                radius: 9
                                color: Theme.field
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: parent.modelData
                                    color: Theme.secondaryText
                                    font.pixelSize: 9
                                }
                            }
                        }
                    }

                    Column {
                        id: analysesTarget
                        objectName: "productTourTargetAnalyses"
                        anchors.left: securitiesTarget.left
                        anchors.right: securitiesTarget.right
                        anchors.top: organizationTarget.bottom
                        anchors.topMargin: 14
                        spacing: 7
                        Repeater {
                            model: ["↗  RS 强度", "⌁  拐点筛选", "◎  极值偏离"]
                            Rectangle {
                                required property string modelData
                                width: analysesTarget.width
                                height: 29
                                radius: 9
                                color: Theme.field
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: parent.modelData
                                    color: Theme.secondaryText
                                    font.pixelSize: 9
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: settingsTarget
                        objectName: "productTourTargetSettings"
                        anchors.left: securitiesTarget.left
                        anchors.right: securitiesTarget.right
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 12
                        height: 31
                        radius: 10
                        color: Theme.field
                        Text {
                            anchors.centerIn: parent
                            text: "⚙  设置与网络"
                            color: Theme.secondaryText
                            font.pixelSize: 9
                        }
                    }
                }

                Item {
                    id: resultsTarget
                    objectName: "productTourTargetResults"
                    x: parent.width * 0.3
                    y: 49
                    width: parent.width * 0.67
                    height: parent.height - 64

                    Text {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: overlay.slide.section
                        color: Theme.text
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 31
                        height: 54
                        radius: 13
                        color: Theme.panel
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: overlay.currentSlide === 3
                                ? "最近结果 · 周期证据 · 信号时间"
                                : "搜索、筛选与本次配置"
                            color: Theme.secondaryText
                            font.pixelSize: 10
                        }
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 96
                        spacing: 8
                        Repeater {
                            model: 3
                            Rectangle {
                                id: resultRow
                                required property int index
                                width: parent.width
                                height: 49
                                radius: 12
                                color: Theme.panel
                                Row {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 12
                                    Rectangle {
                                        width: 23
                                        height: 23
                                        radius: 8
                                        color: resultRow.index === 0
                                            ? Theme.accentSoft : Theme.field
                                    }
                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 4
                                        Rectangle {
                                            width: 124 + resultRow.index * 24
                                            height: 6
                                            radius: 3
                                            color: Theme.secondaryText
                                            opacity: 0.52
                                        }
                                        Rectangle {
                                            width: 82 + resultRow.index * 17
                                            height: 5
                                            radius: 3
                                            color: Theme.faintText
                                            opacity: 0.34
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    id: focusRing
                    objectName: "productTourFocusRing"
                    readonly property point targetOrigin: {
                        const revision = overlay.focusRevision
                        const origin = overlay.focusTarget
                            ? illustration.mapFromItem(
                                overlay.focusTarget, 0, 0)
                            : Qt.point(0, 0)
                        return Qt.point(origin.x + revision * 0, origin.y)
                    }
                    x: targetOrigin.x - 6
                    y: targetOrigin.y - 6
                    width: (overlay.focusTarget ? overlay.focusTarget.width : 0) + 12
                    height: (overlay.focusTarget ? overlay.focusTarget.height : 0) + 12
                    radius: 15
                    color: "transparent"
                    border.width: 3
                    border.color: Theme.accent

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: -7
                        radius: parent.radius + 7
                        color: "transparent"
                        border.width: 7
                        border.color: Theme.accentSoft
                    }

                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ChoiceChip {
                    id: dismissChoice
                    objectName: "productTourDismiss"
                    text: "不再提示"
                }

                Row {
                    Layout.leftMargin: 8
                    spacing: 6
                    Repeater {
                        model: overlay.slides.length
                        Rectangle {
                            required property int index
                            width: index === overlay.currentSlide ? 18 : 7
                            height: 7
                            radius: 4
                            color: index === overlay.currentSlide
                                ? Theme.accent : Theme.hairline
                            Behavior on width { NumberAnimation { duration: 130 } }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                GlassButton {
                    id: previousButton
                    objectName: "productTourPrevious"
                    text: "上一步"
                    enabled: overlay.currentSlide > 0
                    onClicked: overlay.currentSlide -= 1
                }

                GlassButton {
                    id: nextButton
                    objectName: "productTourNext"
                    text: overlay.currentSlide === overlay.slides.length - 1
                        ? "完成" : "下一步"
                    primary: true
                    onClicked: {
                        if (overlay.currentSlide === overlay.slides.length - 1) {
                            overlay.closeTour()
                        } else {
                            overlay.currentSlide += 1
                        }
                    }
                }
            }
        }
    }
}
