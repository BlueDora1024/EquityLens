pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "."
import "components"

Rectangle {
    id: overlay
    objectName: "settingsOverlay"

    signal closeRequested
    signal onboardingCompleted
    signal scenarioRequested
    signal productTourRequested
    property bool firstRunMode: false
    property bool futuGuideOpen: false
    property bool networkSectionFocused: false
    // qmllint disable unqualified
    property var bridge: settingsBridge
    // qmllint enable unqualified

    color: Theme.modalScrim

    FileDialog {
        id: diagnosticExportDialog
        title: "导出诊断包"
        fileMode: FileDialog.SaveFile
        nameFilters: ["诊断包 (*.zip)"]
        onAccepted: overlay.bridge.export_diagnostics(selectedFile)
    }

    function queueAiCheck() {
        if (aiBaseUrl.text.trim().length > 0
                && aiApiKey.text.length > 0
                && !overlay.bridge.busy) {
            aiAutoTimer.restart()
        }
    }

    function pageTitle() {
        return {
            "provider": "行情供应商",
            "ai": "AI 分析",
            "appearance": "外观",
            "advanced": "高级"
        }[overlay.bridge.page] || "设置"
    }

    function pageDescription() {
        return {
            "provider": "选择并验证行情来源；新的集成会在重新构建后自动出现在列表中。",
            "ai": "填写连接信息，其余模型发现、默认选择和能力质检由软件完成。",
            "appearance": "选择跟随系统、浅色或深色；更改会立即应用到整个软件。",
            "advanced": "检查网络与备用行情，管理脱敏诊断和隔离测试工具。"
        }[overlay.bridge.page] || ""
    }

    function focusNetworkSection() {
        overlay.bridge.select_page("advanced")
        overlay.networkSectionFocused = true
        networkFocusTimer.restart()
        Qt.callLater(function() {
            if (advancedScroll.contentItem) {
                advancedScroll.contentItem.contentY = Math.max(
                    0, networkFallbackPanel.y - 8)
            }
        })
    }

    MouseArea { anchors.fill: parent }

    Timer {
        id: aiAutoTimer
        interval: 550
        repeat: false
        onTriggered: overlay.bridge.auto_configure_ai(
            aiBaseUrl.text, aiApiKey.text)
    }

    Timer {
        id: networkFocusTimer
        interval: 1400
        repeat: false
        onTriggered: overlay.networkSectionFocused = false
    }

    Connections {
        // qmllint disable unqualified
        target: overlay.bridge
        function onAi_ready() {
            aiApiKey.clear()
            if (overlay.firstRunMode
                    && overlay.bridge.complete_first_run()) {
                overlay.onboardingCompleted()
            }
        }
        function onReset_completed() {
            aiApiKey.clear()
            resetConfirmation.clear()
        }
        function onFutu_guidance_requested() {
            overlay.futuGuideOpen = true
        }
        // qmllint enable unqualified
    }

    GlassPanel {
        width: overlay.firstRunMode
            ? overlay.width
            : Math.min(1040, overlay.width - 48)
        height: overlay.firstRunMode
            ? overlay.height
            : Math.min(680, overlay.height - 48)
        anchors.centerIn: parent
        color: Theme.dark ? "#F021242A" : "#FAF5F4F1"

        RowLayout {
            anchors.fill: parent
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 184
                Layout.fillHeight: true
                radius: Theme.panelRadius
                color: Theme.sidebar

                Column {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 8

                    Text {
                        text: overlay.firstRunMode ? "开始使用" : "设置"
                        color: Theme.text
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                        bottomPadding: 14
                    }
                    SidebarItem {
                        width: parent.width
                        glyph: "⌁"
                        text: "行情供应商"
                        // qmllint disable unqualified
                        selected: overlay.bridge.page === "provider"
                        onClicked: overlay.bridge.select_page("provider")
                        // qmllint enable unqualified
                    }
                    SidebarItem {
                        width: parent.width
                        glyph: "✦"
                        text: "AI 分析"
                        enabled: !overlay.firstRunMode
                            || overlay.bridge.provider_configured
                        // qmllint disable unqualified
                        selected: overlay.bridge.page === "ai"
                        onClicked: overlay.bridge.select_page("ai")
                        // qmllint enable unqualified
                    }
                    SidebarItem {
                        width: parent.width
                        visible: !overlay.firstRunMode
                        glyph: "◐"
                        text: "外观"
                        // qmllint disable unqualified
                        selected: overlay.bridge.page === "appearance"
                        onClicked: overlay.bridge.select_page("appearance")
                        // qmllint enable unqualified
                    }
                    SidebarItem {
                        width: parent.width
                        visible: !overlay.firstRunMode
                        glyph: "⌘"
                        text: "高级"
                        // qmllint disable unqualified
                        selected: overlay.bridge.page === "advanced"
                        onClicked: overlay.bridge.select_page("advanced")
                        // qmllint enable unqualified
                    }
                }

                GlassButton {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.bottom: footer.top
                    anchors.bottomMargin: 12
                    text: "恢复默认…"
                    visible: !overlay.firstRunMode
                    onClicked: overlay.bridge.request_reset()
                }
                Text {
                    id: footer
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 18
                    text: "本机数据 · 私有"
                    color: Theme.faintText
                    font.pixelSize: 10
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                GlassButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 20
                    anchors.top: parent.top
                    anchors.topMargin: 18
                    text: "完成"
                    visible: !overlay.firstRunMode
                    onClicked: overlay.closeRequested()
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    anchors.topMargin: 42
                    spacing: 10

                    Text {
                        text: overlay.pageTitle()
                        color: Theme.text
                        font.pixelSize: 25
                        font.weight: Font.Bold
                    }

                    Text {
                        Layout.fillWidth: true
                        text: overlay.pageDescription()
                        color: Theme.secondaryText
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        id: providerSettingsPage
                        objectName: "providerSettingsPage"
                        visible: overlay.bridge.page === "provider"
                        enabled: visible
                        opacity: visible ? 1 : 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: 4
                        spacing: 12

                        GlassPanel {
                            Layout.preferredWidth: 204
                            Layout.fillHeight: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 8

                                Text {
                                    text: "已发现"
                                    color: Theme.secondaryText
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                }
                                ListView {
                                    id: providerCatalog
                                    objectName: "providerCatalog"
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 7
                                    clip: true
                                    // qmllint disable unqualified
                                    model: overlay.bridge.providers
                                    // qmllint enable unqualified

                                    delegate: Rectangle {
                                        id: providerCard
                                        required property var modelData
                                        width: providerCatalog.width
                                        height: 76
                                        radius: 13
                                        color: overlay.bridge.selected_provider_id
                                            === modelData.id
                                            ? Theme.accentSoft : Theme.field
                                        border.width: 1
                                        border.color: Theme.hairline

                                        Column {
                                            anchors.left: parent.left
                                            anchors.right: statusDot.left
                                            anchors.margins: 12
                                            anchors.rightMargin: 8
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: 4

                                            Text {
                                                text: providerCard.modelData.name
                                                color: Theme.text
                                                font.pixelSize: 14
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                width: parent.width
                                                text: providerCard.modelData.summary
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                            }
                                        }
                                        Rectangle {
                                            id: statusDot
                                            width: 8
                                            height: 8
                                            radius: 4
                                            anchors.right: parent.right
                                            anchors.rightMargin: 12
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: providerCard.modelData.active
                                                ? Theme.accent
                                                : (providerCard.modelData.configured
                                                    ? Theme.success
                                                    : Theme.faintText)
                                        }
                                        MouseArea {
                                            anchors.fill: parent
                                            onClicked: overlay.bridge.select_provider(
                                                providerCard.modelData.id)
                                        }
                                    }
                                }

                                GlassButton {
                                    objectName: "providerAddCard"
                                    Layout.fillWidth: true
                                    text: "＋  接入供应商"
                                    primary: overlay.bridge.selected_provider_id === "add"
                                    onClicked: overlay.bridge.select_provider("add")
                                }
                            }
                        }

                        GlassPanel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            Item {
                                anchors.fill: parent
                                visible: overlay.bridge.selected_provider_id
                                    === "longbridge"

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        ColumnLayout {
                                            spacing: 2
                                            Text {
                                                text: "长桥 · Longbridge"
                                                color: Theme.text
                                                font.pixelSize: 18
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                text: "内置 · 官方 OpenAPI"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: overlay.bridge.active_provider_id
                                                === "longbridge"
                                                ? "●  当前供应商"
                                                : (overlay.bridge
                                                    .selected_provider_quality_passed
                                                    ? "●  已通过质检"
                                                    : "○  等待配置")
                                            color: overlay.bridge
                                                .selected_provider_quality_passed
                                                ? Theme.success : Theme.secondaryText
                                            font.pixelSize: 11
                                        }
                                    }

                                    GlassPanel {
                                        id: longbridgeQuality
                                        objectName: "longbridgeQuality"
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 198

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 14
                                            spacing: 6

                                            Text {
                                                text: "授权与自检"
                                                color: Theme.text
                                                font.pixelSize: 13
                                                font.weight: Font.DemiBold
                                            }
                                            Repeater {
                                                model: overlay.bridge.provider_checks
                                                delegate: RowLayout {
                                                    id: checkRow
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    spacing: 9

                                                    Rectangle {
                                                        Layout.preferredWidth: 20
                                                        Layout.preferredHeight: 20
                                                        radius: 10
                                                        color: checkRow.modelData.state
                                                            === "passed"
                                                            ? Theme.successSoft
                                                            : (checkRow.modelData.state
                                                                === "failed"
                                                                ? Theme.warmGlow
                                                                : Theme.field)
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: checkRow.modelData.state
                                                                === "passed" ? "✓"
                                                                : (checkRow.modelData.state
                                                                    === "failed" ? "!" : "·")
                                                            color: checkRow.modelData.state
                                                                === "passed"
                                                                ? Theme.success
                                                                : Theme.secondaryText
                                                            font.pixelSize: 11
                                                        }
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: checkRow.modelData.label
                                                        color: Theme.text
                                                        font.pixelSize: 11
                                                    }
                                                    Text {
                                                        text: checkRow.modelData.state
                                                            === "passed" ? "通过"
                                                            : (checkRow.modelData.state
                                                                === "checking" ? "检查中"
                                                                : (checkRow.modelData.state
                                                                    === "failed" ? "失败" : "待检查"))
                                                        color: checkRow.modelData.state
                                                            === "passed"
                                                            ? Theme.success
                                                            : Theme.secondaryText
                                                        font.pixelSize: 10
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        GlassButton {
                                            objectName: "providerAuthorizeButton"
                                            text: overlay.bridge.busy_action
                                                === "provider_authorize"
                                                ? "等待浏览器授权…" : "打开长桥授权"
                                            enabled: !overlay.bridge.busy
                                            onClicked: overlay.bridge.authorize_provider()
                                        }
                                        BusySpinner {
                                            visible: overlay.bridge.busy_action
                                                === "provider_authorize"
                                            running: visible
                                        }
                                        GlassButton {
                                            id: providerQualityButton
                                            objectName: "providerQualityButton"
                                            text: overlay.bridge.busy_action
                                                === "provider_quality"
                                                ? "正在质检…" : "我已完成授权，开始自检"
                                            primary: overlay.bridge.provider_authorized_pending
                                            enabled: !overlay.bridge.busy
                                                && (overlay.bridge
                                                    .provider_authorized_pending
                                                    || overlay.bridge
                                                        .selected_provider_quality_passed)
                                            onClicked: overlay.bridge.quality_provider()
                                        }
                                        BusySpinner {
                                            objectName: "providerQualitySpinner"
                                            visible: overlay.bridge.busy_action
                                                === "provider_quality"
                                            running: visible
                                        }
                                        Item { Layout.fillWidth: true }
                                        GlassButton {
                                            id: longbridgeActivateButton
                                            objectName: "longbridgeActivateButton"
                                            text: overlay.bridge.active_provider_id
                                                === "longbridge"
                                                ? "已设为当前供应商"
                                                : (overlay.bridge.busy_action
                                                    === "provider_activate"
                                                    ? "切换中…"
                                                    : "设为当前供应商")
                                            primary: overlay.bridge
                                                .selected_provider_quality_passed
                                                && overlay.bridge
                                                    .active_provider_id
                                                    !== "longbridge"
                                            enabled: !overlay.bridge.busy
                                                && overlay.bridge
                                                    .selected_provider_quality_passed
                                                && overlay.bridge
                                                    .active_provider_id
                                                    !== "longbridge"
                                            onClicked: overlay.bridge
                                                .activate_selected_provider()
                                        }
                                    }

                                    GlassPanel {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 13
                                            spacing: 5

                                            Text {
                                                text: "工作原理"
                                                color: Theme.text
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: "软件动态注册 OAuth 客户端并打开长桥官方授权页，仅保留基础数据和最低风险的自选列表权限，不申请账户资产、资金明细、订单查询或下单权限。官方 SDK 将 Token 保存在 ~/.longbridge/openapi/tokens/<client_id> 并自动刷新；本软件只在 SQLite 保存 Client ID，不读取或记录 Token 内容。"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                                wrapMode: Text.WordWrap
                                            }
                                            Text {
                                                text: "查看 Longbridge OAuth 参考说明  ↗"
                                                color: Theme.accent
                                                font.pixelSize: 10
                                                font.underline: true
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: Qt.openUrlExternally(
                                                        overlay.bridge
                                                            .provider_reference_url)
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Item {
                                id: futuProviderPanel
                                objectName: "futuProviderPanel"
                                anchors.fill: parent
                                visible: overlay.bridge.selected_provider_id
                                    === "futu"

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        ColumnLayout {
                                            spacing: 2
                                            Text {
                                                text: "富途 · Futu"
                                                color: Theme.text
                                                font.pixelSize: 18
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                text: "内置 · 连接本机 Futu OpenD"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                            }
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: overlay.bridge.active_provider_id
                                                === "futu"
                                                ? "●  当前供应商"
                                                : (overlay.bridge
                                                    .selected_provider_quality_passed
                                                    ? "●  已通过质检"
                                                    : "○  等待配置")
                                            color: overlay.bridge
                                                .selected_provider_quality_passed
                                                ? Theme.success
                                                : Theme.secondaryText
                                            font.pixelSize: 11
                                        }
                                    }

                                    GlassPanel {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 238

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 14
                                            spacing: 6

                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text {
                                                    text: "OpenD 连接与只读质检"
                                                    color: Theme.text
                                                    font.pixelSize: 13
                                                    font.weight: Font.DemiBold
                                                }
                                                Item { Layout.fillWidth: true }
                                                GlassButton {
                                                    text: "查看连接步骤"
                                                    onClicked: overlay
                                                        .futuGuideOpen = true
                                                }
                                            }
                                            Repeater {
                                                model: overlay.bridge
                                                    .provider_checks
                                                delegate: RowLayout {
                                                    id: futuCheckRow
                                                    required property var modelData
                                                    Layout.fillWidth: true
                                                    spacing: 9

                                                    Rectangle {
                                                        Layout.preferredWidth: 20
                                                        Layout.preferredHeight: 20
                                                        radius: 10
                                                        color: futuCheckRow
                                                            .modelData.state
                                                            === "passed"
                                                            ? Theme.successSoft
                                                            : (futuCheckRow
                                                                .modelData.state
                                                                === "failed"
                                                                ? Theme.warmGlow
                                                                : Theme.field)
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: futuCheckRow
                                                                .modelData.state
                                                                === "passed" ? "✓"
                                                                : (futuCheckRow
                                                                    .modelData.state
                                                                    === "failed" ? "!" : "·")
                                                            color: futuCheckRow
                                                                .modelData.state
                                                                === "passed"
                                                                ? Theme.success
                                                                : Theme.secondaryText
                                                            font.pixelSize: 11
                                                        }
                                                    }
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: futuCheckRow
                                                            .modelData.label
                                                        color: Theme.text
                                                        font.pixelSize: 11
                                                    }
                                                    Text {
                                                        text: futuCheckRow
                                                            .modelData.state
                                                            === "passed" ? "通过"
                                                            : (futuCheckRow
                                                                .modelData.state
                                                                === "checking" ? "检查中"
                                                                : (futuCheckRow
                                                                    .modelData.state
                                                                    === "failed" ? "失败"
                                                                    : "待检查"))
                                                        color: futuCheckRow
                                                            .modelData.state
                                                            === "passed"
                                                            ? Theme.success
                                                            : Theme.secondaryText
                                                        font.pixelSize: 10
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        GlassButton {
                                            id: futuOpenButton
                                            objectName: "futuOpenButton"
                                            text: "打开 Futu OpenD"
                                            enabled: !overlay.bridge.busy
                                            onClicked: overlay.bridge
                                                .open_futu_opend()
                                        }
                                        GlassButton {
                                            id: futuQualityButton
                                            objectName: "futuQualityButton"
                                            text: overlay.bridge.busy_action
                                                === "provider_quality"
                                                ? "正在质检…" : "我已登录，开始质检"
                                            primary: !overlay.bridge
                                                .selected_provider_quality_passed
                                            enabled: !overlay.bridge.busy
                                            onClicked: overlay.bridge
                                                .quality_provider()
                                        }
                                        BusySpinner {
                                            visible: overlay.bridge.busy_action
                                                === "provider_quality"
                                            running: visible
                                        }
                                        Item { Layout.fillWidth: true }
                                        GlassButton {
                                            id: futuActivateButton
                                            objectName: "futuActivateButton"
                                            text: overlay.bridge.active_provider_id
                                                === "futu"
                                                ? "已设为当前供应商"
                                                : (overlay.bridge.busy_action
                                                    === "provider_activate"
                                                    ? "切换中…"
                                                    : "设为当前供应商")
                                            primary: overlay.bridge
                                                .selected_provider_quality_passed
                                                && overlay.bridge
                                                    .active_provider_id
                                                    !== "futu"
                                            enabled: !overlay.bridge.busy
                                                && overlay.bridge
                                                    .selected_provider_quality_passed
                                                && overlay.bridge
                                                    .active_provider_id
                                                    !== "futu"
                                            onClicked: overlay.bridge
                                                .activate_selected_provider()
                                        }
                                    }

                                    Text {
                                        id: futuQualityStatus
                                        objectName: "futuQualityStatus"
                                        Layout.fillWidth: true
                                        visible: overlay.bridge.status.length > 0
                                        text: overlay.bridge.status
                                        color: overlay.bridge.status.indexOf("通过") >= 0
                                            ? Theme.success : Theme.secondaryText
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }

                                    GlassPanel {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true

                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 13
                                            spacing: 5
                                            Text {
                                                text: "连接边界"
                                                color: Theme.text
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: "软件只连接 127.0.0.1:11111 的本机 OpenD，读取证券资料、行情、交易日和历史 K 线；账号登录由 OpenD 完成。本软件不保存富途账号，不创建交易连接，不接入交易、资产、持仓或订单。"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                                wrapMode: Text.WordWrap
                                            }
                                        }
                                    }
                                }
                            }

                            Item {
                                anchors.fill: parent
                                visible: overlay.bridge.selected_provider_id === "add"

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 9

                                    Text {
                                        text: "接入新供应商"
                                        color: Theme.text
                                        font.pixelSize: 18
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "这是开发接入规范，不会加载未经审查的本机脚本。把下面提示词交给其他 AI；实现注册并重新构建后，软件会自动发现新供应商。"
                                        color: Theme.secondaryText
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                    }
                                    TextArea {
                                        id: providerPrompt
                                        objectName: "providerPrompt"
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        text: overlay.bridge.provider_prompt
                                        readOnly: true
                                        selectByMouse: true
                                        wrapMode: TextEdit.Wrap
                                        color: Theme.text
                                        selectionColor: Theme.accent
                                        selectedTextColor: "#FFFFFF"
                                        font.pixelSize: 10
                                        padding: 12
                                        background: Rectangle {
                                            radius: Theme.controlRadius
                                            color: Theme.field
                                            border.width: 1
                                            border.color: Theme.hairline
                                        }
                                    }
                                    RowLayout {
                                        Item { Layout.fillWidth: true }
                                        GlassButton {
                                            text: "重新扫描"
                                            onClicked: overlay.bridge.refresh_providers()
                                        }
                                        GlassButton {
                                            text: "复制开发提示词"
                                            primary: true
                                            onClicked: overlay.bridge
                                                .copy_provider_prompt()
                                        }
                                    }
                                }
                            }
                        }
                    }

                    ScrollView {
                        id: aiSettingsPage
                        objectName: "aiSettingsPage"
                        visible: overlay.bridge.page === "ai"
                        enabled: visible
                        opacity: visible ? 1 : 0
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth

                        ColumnLayout {
                            objectName: "aiSettingsContent"
                            width: aiSettingsPage.width
                            spacing: 10

                            GlassPanel {
                                objectName: "aiConnectionPanel"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 214

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 8

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: "1  连接"
                                            color: Theme.text
                                            font.pixelSize: 14
                                            font.weight: Font.DemiBold
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text {
                                            text: overlay.bridge.ai_configured
                                                ? "●  已配置" : "填写两项后自动继续"
                                            color: overlay.bridge.ai_configured
                                                ? Theme.success : Theme.secondaryText
                                            font.pixelSize: 10
                                        }
                                    }
                                    RowLayout {
                                        id: aiConnectionFields
                                        objectName: "aiConnectionFields"
                                        readonly property real fieldWidth:
                                            Math.max(
                                                0,
                                                (parent.width - spacing) / 2)
                                        Layout.fillWidth: true
                                        spacing: 8
                                        ColumnLayout {
                                            Layout.minimumWidth:
                                                aiConnectionFields.fieldWidth
                                            Layout.preferredWidth:
                                                aiConnectionFields.fieldWidth
                                            Layout.maximumWidth:
                                                aiConnectionFields.fieldWidth
                                            spacing: 4
                                            Text {
                                                text: "Base URL"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                            }
                                            GlassTextInput {
                                                id: aiBaseUrl
                                                objectName: "aiBaseUrl"
                                                Layout.fillWidth: true
                                                text: overlay.bridge.ai_base_url
                                                placeholderText: "https://…/v1"
                                                onEditingFinished: overlay
                                                    .queueAiCheck()
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.minimumWidth:
                                                aiConnectionFields.fieldWidth
                                            Layout.preferredWidth:
                                                aiConnectionFields.fieldWidth
                                            Layout.maximumWidth:
                                                aiConnectionFields.fieldWidth
                                            spacing: 4
                                            Text {
                                                text: "API Key"
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                            }
                                            GlassTextInput {
                                                id: aiApiKey
                                                objectName: "aiApiKey"
                                                Layout.fillWidth: true
                                                secret: true
                                                placeholderText: overlay.bridge
                                                    .api_key_hint
                                                onEditingFinished: overlay
                                                    .queueAiCheck()
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Text {
                                            Layout.fillWidth: true
                                            text: "使用 DeepSeek？推荐先充值 10 元，"
                                                + "创建 API Key 通常 2–3 分钟即可完成。"
                                            color: Theme.secondaryText
                                            font.pixelSize: 10
                                            wrapMode: Text.WordWrap
                                        }
                                        GlassButton {
                                            text: "打开 DeepSeek API Keys"
                                            onClicked: Qt.openUrlExternally(
                                                overlay.bridge
                                                    .deepseek_api_keys_url)
                                        }
                                    }
                                    RowLayout {
                                        objectName: "aiConnectionActions"
                                        Layout.fillWidth: true
                                        Text {
                                            Layout.fillWidth: true
                                            text: "兼容 OpenAI / DeepSeek 等 OpenAI-compatible 接口"
                                            color: Theme.faintText
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignLeft
                                        }
                                        GlassButton {
                                            id: aiAutoCheckButton
                                            objectName: "aiAutoCheckButton"
                                            text: overlay.bridge.busy
                                                ? "检测中…" : "自动检测并配置"
                                            primary: aiBaseUrl.text.trim().length > 0
                                                && aiApiKey.text.length > 0
                                            enabled: !overlay.bridge.busy
                                                && aiBaseUrl.text.trim().length > 0
                                                && aiApiKey.text.length > 0
                                            busy: overlay.bridge.busy_action === "ai_setup"
                                            onClicked: overlay.bridge.auto_configure_ai(
                                                aiBaseUrl.text, aiApiKey.text)
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                GlassPanel {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.preferredHeight: 126
                                    opacity: overlay.bridge.models.length > 0
                                        || overlay.bridge.ai_configured ? 1 : 0.48

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        spacing: 7
                                        Text {
                                            text: "2  可用模型"
                                            color: Theme.text
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }
                                        GlassField {
                                            id: aiModelSelect
                                            objectName: "aiModelSelect"
                                            Layout.fillWidth: true
                                            enabled: overlay.bridge.ai_configured
                                                && !overlay.bridge.busy
                                            model: overlay.bridge.models
                                            loading: overlay.bridge.busy_action
                                                === "ai_models"
                                            loaded: overlay.bridge.models.length > 0
                                            emptyText: "未发现其他模型"
                                            valueText: overlay.bridge.models.length > 0
                                                || overlay.bridge.ai_configured
                                                ? overlay.bridge.ai_model
                                                : "待发现模型"
                                            onOpening: {
                                                if (overlay.bridge.models.length === 0
                                                        && overlay.bridge.ai_configured) {
                                                    overlay.bridge.refresh_ai_models()
                                                }
                                            }
                                            onActivated: {
                                                var selected = textAt(currentIndex)
                                                overlay.bridge.select_ai_model(selected)
                                            }
                                        }
                                    }
                                }

                                GlassPanel {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.preferredHeight: 126
                                    opacity: overlay.bridge.ai_configured ? 1 : 0.48

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        spacing: 7
                                        Text {
                                            text: "3  能力质检"
                                            color: Theme.text
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: overlay.bridge.ai_configured
                                                ? "✓  模型已完成 IREN 结构化分类"
                                                : "等待模型发现后自动执行"
                                            color: overlay.bridge.ai_configured
                                                ? Theme.success : Theme.secondaryText
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                        }
                                        GlassButton {
                                            text: overlay.bridge.busy_action
                                                === "ai_quality"
                                                ? "质检中…" : "重新质检"
                                            enabled: overlay.bridge.ai_configured
                                                && !overlay.bridge.busy
                                            onClicked: overlay.bridge.quality_ai(
                                                aiBaseUrl.text,
                                                overlay.bridge.ai_model, "")
                                        }
                                        BusySpinner {
                                            visible: overlay.bridge.busy_action
                                                === "ai_quality"
                                            running: visible
                                        }
                                    }
                                }
                            }

                            GlassPanel {
                                id: aiCapabilityPanel
                                objectName: "aiCapabilityPanel"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 166

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 15
                                    spacing: 6
                                    Text {
                                        text: "AI 会参与什么"
                                        color: Theme.text
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "• 供应商无法确定时，兜底判断美股普通股 / ADR，并排除 ETF、REIT 与加密合约。\n• 根据公司描述提出最多三个全局分类，供人工维护和股票池评审绑定。\n• 仅在你点击时生成极值偏离解读，并随历史冻结。"
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                        lineHeight: 1.18
                                        wrapMode: Text.WordWrap
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "不设置 AI：行情和三个确定性算法仍可运行；无法确认类型的证券不会导入，自动分类与极值偏离 AI 解读不可用。"
                                        color: Theme.faintText
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                        }
                    }

                    GlassPanel {
                        visible: overlay.bridge.page === "appearance"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 250
                        Layout.alignment: Qt.AlignTop

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 12

                            Text {
                                text: "主题模式"
                                color: Theme.text
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            Text {
                                Layout.fillWidth: true
                                text: "跟随系统会随 macOS 外观自动切换。浅色和深色会保持固定，直到你再次修改。"
                                color: Theme.secondaryText
                                font.pixelSize: 11
                                wrapMode: Text.WordWrap
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                // qmllint disable unqualified
                                GlassButton {
                                    objectName: "appearanceMode_system"
                                    Layout.fillWidth: true
                                    text: "跟随系统"
                                    primary: themeBridge.mode === "system"
                                    onClicked: themeBridge.set_mode("system")
                                }
                                GlassButton {
                                    objectName: "appearanceMode_light"
                                    Layout.fillWidth: true
                                    text: "浅色"
                                    primary: themeBridge.mode === "light"
                                    onClicked: themeBridge.set_mode("light")
                                }
                                GlassButton {
                                    objectName: "appearanceMode_dark"
                                    Layout.fillWidth: true
                                    text: "深色"
                                    primary: themeBridge.mode === "dark"
                                    onClicked: themeBridge.set_mode("dark")
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: themeBridge.mode === "system"
                                    ? "当前：跟随系统"
                                    : (themeBridge.mode === "light"
                                        ? "当前：固定浅色" : "当前：固定深色")
                                color: Theme.secondaryText
                                font.pixelSize: 11
                            }
                            // qmllint enable unqualified

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                color: Theme.hairline
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3
                                    Text {
                                        text: "使用引导"
                                        color: Theme.text
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "随时重新查看证券库、股票池、分析工具与网络设置的五步说明。"
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                GlassButton {
                                    objectName: "appearanceProductTourButton"
                                    text: "再次查看引导"
                                    onClicked: overlay.productTourRequested()
                                }
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    ScrollView {
                        id: advancedScroll
                        visible: overlay.bridge.page === "advanced"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        contentWidth: availableWidth

                        ColumnLayout {
                            width: advancedScroll.availableWidth
                            spacing: 10

                        GlassPanel {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 350

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 9

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "诊断日志"
                                        color: Theme.text
                                        font.pixelSize: 14
                                        font.weight: Font.DemiBold
                                    }
                                    BusySpinner {
                                        running: overlay.bridge
                                            .diagnostic_loading
                                        visible: running
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        text: overlay.bridge.diagnostic_status
                                        color: overlay.bridge
                                            .diagnostic_status === "正常"
                                            ? Theme.success
                                            : Theme.secondaryText
                                        font.pixelSize: 11
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "记录关键操作、耗时、内存、卡顿与慢查询；不会记录 API Key、Token 或请求正文。"
                                    color: Theme.secondaryText
                                    font.pixelSize: 10
                                    wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 18
                                    Text {
                                        text: "保留 7 天 · 上限 100 MB"
                                        color: Theme.text
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        text: "占用 "
                                            + overlay.bridge
                                                .diagnostic_size_text
                                        color: Theme.secondaryText
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        text: overlay.bridge
                                            .diagnostic_summary
                                        color: Theme.secondaryText
                                        font.pixelSize: 11
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    GlassField {
                                        id: diagnosticModuleFilter
                                        Layout.preferredWidth: 150
                                        model: [
                                            {"id": "",
                                                "name": "全部模块"},
                                            {"id": "operations",
                                                "name": "任务"},
                                            {"id": "sqlite",
                                                "name": "SQLite"},
                                            {"id": "ui",
                                                "name": "界面"},
                                            {"id": "network",
                                                "name": "网络"}
                                        ]
                                        textRole: "name"
                                        valueRole: "id"
                                        valueText: currentText
                                            || "全部模块"
                                        onActivated: overlay.bridge
                                            .refresh_diagnostics(
                                                currentValue,
                                                diagnosticLevelFilter
                                                    .currentValue,
                                                diagnosticSearch.text)
                                    }
                                    GlassField {
                                        id: diagnosticLevelFilter
                                        Layout.preferredWidth: 130
                                        model: [
                                            {"id": "",
                                                "name": "全部级别"},
                                            {"id": "warning",
                                                "name": "警告"},
                                            {"id": "error",
                                                "name": "错误"}
                                        ]
                                        textRole: "name"
                                        valueRole: "id"
                                        valueText: currentText
                                            || "全部级别"
                                        onActivated: overlay.bridge
                                            .refresh_diagnostics(
                                                diagnosticModuleFilter
                                                    .currentValue,
                                                currentValue,
                                                diagnosticSearch.text)
                                    }
                                    GlassTextInput {
                                        id: diagnosticSearch
                                        Layout.fillWidth: true
                                        placeholderText: "搜索 ticker / 任务 ID / 错误码"
                                        onAccepted: overlay.bridge
                                            .refresh_diagnostics(
                                                diagnosticModuleFilter
                                                    .currentValue,
                                                diagnosticLevelFilter
                                                    .currentValue,
                                                text)
                                    }
                                    GlassButton {
                                        text: "刷新"
                                        enabled: !overlay.bridge
                                            .diagnostic_loading
                                        onClicked: overlay.bridge
                                            .refresh_diagnostics(
                                                diagnosticModuleFilter
                                                    .currentValue,
                                                diagnosticLevelFilter
                                                    .currentValue,
                                                diagnosticSearch.text)
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 118
                                    radius: Theme.controlRadius
                                    color: Theme.field
                                    border.width: 1
                                    border.color: Theme.hairline

                                    ListView {
                                        id: diagnosticEventList
                                        anchors.fill: parent
                                        anchors.margins: 6
                                        spacing: 3
                                        clip: true
                                        model: overlay.bridge.diagnostic_events

                                        delegate: Rectangle {
                                            required property var modelData
                                            width: diagnosticEventList.width
                                            height: 32
                                            radius: 8
                                            color: Theme.panel

                                            Text {
                                                anchors.fill: parent
                                                anchors.leftMargin: 10
                                                anchors.rightMargin: 10
                                                text: (parent.modelData
                                                        .timestamp || "")
                                                    + "  "
                                                    + (parent.modelData
                                                        .module || "")
                                                    + " · "
                                                    + (parent.modelData
                                                        .action || "")
                                                    + (parent.modelData
                                                        .ticker
                                                        ? " · "
                                                            + parent
                                                                .modelData
                                                                .ticker
                                                        : "")
                                                color: Theme.secondaryText
                                                font.pixelSize: 10
                                                elide: Text.ElideRight
                                                verticalAlignment:
                                                    Text.AlignVCenter
                                            }
                                        }

                                        Text {
                                            anchors.centerIn: parent
                                            visible: !overlay.bridge
                                                .diagnostic_loading
                                                && diagnosticEventList
                                                    .count === 0
                                            text: "暂无匹配日志"
                                            color: Theme.faintText
                                            font.pixelSize: 11
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    GlassButton {
                                        text: "打开日志目录"
                                        onClicked: overlay.bridge
                                            .open_diagnostics_folder()
                                    }
                                    GlassButton {
                                        text: "导出诊断包"
                                        primary: true
                                        enabled: !overlay.bridge
                                            .diagnostic_loading
                                        onClicked: {
                                            diagnosticExportDialog
                                                .currentFile =
                                                overlay.bridge
                                                    .diagnostic_export_default_url
                                            diagnosticExportDialog.open()
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                    GlassButton {
                                        text: "清空日志…"
                                        enabled: !overlay.bridge
                                            .diagnostic_loading
                                        onClicked: overlay.bridge.request_clear_diagnostics()
                                    }
                                }
                            }
                        }

                        GlassPanel {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 112

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 10

                                Text {
                                    text: "日期与时间"
                                    color: Theme.text
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        Layout.fillWidth: true
                                        text: "历史、信号和导出时间按此时区显示；算法仍使用原始行情时间。"
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                    }
                                    GlassField {
                                        Layout.preferredWidth: 220
                                        model: [
                                            {"id": "Asia/Shanghai",
                                                "name": "北京时间"},
                                            {"id": "America/New_York",
                                                "name": "美东时间"},
                                            {"id": "system",
                                                "name": "跟随系统时区"}
                                        ]
                                        textRole: "name"
                                        valueRole: "id"
                                        valueText: {
                                            const names = {
                                                "Asia/Shanghai": "北京时间",
                                                "America/New_York": "美东时间",
                                                "system": "跟随系统时区"
                                            }
                                            return names[overlay.bridge
                                                .display_timezone]
                                                || "北京时间"
                                        }
                                        onActivated: overlay.bridge.save_network(
                                            currentValue,
                                            overlay.bridge.proxy_mode,
                                            "")
                                    }
                                }
                            }
                        }

                        GlassPanel {
                            id: networkFallbackPanel
                            objectName: "networkFallbackPanel"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 274
                            border.width: 1
                            border.color: overlay.networkSectionFocused
                                ? Theme.accent : Theme.hairline

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 9

                                RowLayout {
                                    Layout.fillWidth: true
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2
                                        Text {
                                            text: "网络与备用行情"
                                            color: Theme.text
                                            font.pixelSize: 14
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: "先确认网络路径，再验证 Yahoo 能否读取 NVDA 日线。"
                                            color: Theme.secondaryText
                                            font.pixelSize: 10
                                        }
                                    }
                                    Text {
                                        text: "⌁"
                                        color: Theme.accent
                                        font.pixelSize: 16
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    GlassButton {
                                        text: "不使用代理"
                                        primary: overlay.bridge.proxy_mode
                                            === "off"
                                        onClicked: overlay.bridge.save_network(
                                            overlay.bridge.display_timezone,
                                            "off", "")
                                    }
                                    GlassButton {
                                        text: "跟随系统代理"
                                        primary: overlay.bridge.proxy_mode
                                            === "system"
                                        onClicked: overlay.bridge.save_network(
                                            overlay.bridge.display_timezone,
                                            "system", "")
                                    }
                                    GlassButton {
                                        text: "自定义代理"
                                        primary: overlay.bridge.proxy_mode
                                            === "custom"
                                        onClicked: {
                                            if (overlay.bridge.proxy_url_hint) {
                                                overlay.bridge.save_network(
                                                    overlay.bridge
                                                        .display_timezone,
                                                    "custom", "")
                                            } else {
                                                proxyUrlInput.forceActiveFocus()
                                            }
                                        }
                                    }
                                    Item { Layout.fillWidth: true }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    GlassTextInput {
                                        id: proxyUrlInput
                                        objectName: "proxyUrlInput"
                                        Layout.fillWidth: true
                                        placeholderText: overlay.bridge
                                            .proxy_url_hint
                                            || "http://127.0.0.1:7890"
                                    }
                                    GlassButton {
                                        text: "保存"
                                        enabled: proxyUrlInput.text.trim()
                                            .length > 0
                                        onClicked: {
                                            if (overlay.bridge.save_network(
                                                    overlay.bridge
                                                        .display_timezone,
                                                    "custom",
                                                    proxyUrlInput.text)) {
                                                proxyUrlInput.clear()
                                            }
                                        }
                                    }
                                    GlassButton {
                                        objectName: "proxyQualityButton"
                                        text: overlay.bridge.busy_action
                                            === "proxy_quality"
                                            ? "检查中…" : "检查网络代理"
                                        enabled: !overlay.bridge.busy
                                        onClicked: overlay.bridge.quality_proxy()
                                    }
                                    GlassButton {
                                        objectName: "yahooQualityButton"
                                        text: overlay.bridge.busy_action
                                            === "yahoo_quality"
                                            ? "检查中…" : "检查 Yahoo 备用行情"
                                        enabled: !overlay.bridge.busy
                                        onClicked: overlay.bridge.quality_yahoo()
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Text {
                                        text: overlay.bridge.yahoo_quality_state
                                            === "passed" ? "✓" : (overlay.bridge
                                                .yahoo_quality_state === "failed"
                                                ? "!" : "○")
                                        color: overlay.bridge.yahoo_quality_state
                                            === "passed" ? Theme.success
                                            : (overlay.bridge.yahoo_quality_state
                                                === "failed" ? Theme.danger
                                                : Theme.faintText)
                                        font.pixelSize: 11
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Yahoo · "
                                            + overlay.bridge.yahoo_quality_detail
                                            + (overlay.bridge.yahoo_quality_checked_at
                                                ? " · " + overlay.bridge
                                                    .yahoo_quality_checked_at : "")
                                        color: Theme.secondaryText
                                        font.pixelSize: 10
                                    }
                                    Text {
                                        text: "支持 HTTP、HTTPS、SOCKS5 · 凭据已脱敏"
                                        color: Theme.faintText
                                        font.pixelSize: 9
                                    }
                                }
                            }
                        }

                        GlassPanel {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 142

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 10
                                Text {
                                    text: "开发者工具"
                                    color: Theme.text
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: "Scenario Lab 使用内置 Mock Provider 和临时数据库，不接触正式数据。"
                                    color: Theme.secondaryText
                                    font.pixelSize: 10
                                }
                                RowLayout {
                                    ChoiceChip {
                                        text: "启用开发者模式"
                                        checked: overlay.bridge
                                            .developer_mode_enabled
                                        onToggled: overlay.bridge
                                            .set_developer_mode(checked)
                                    }
                                    GlassButton {
                                        text: "打开 Scenario Lab"
                                        primary: true
                                        enabled: overlay.bridge
                                            .developer_mode_enabled
                                        onClicked: overlay.scenarioRequested()
                                    }
                                }
                            }
                        }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: overlay.bridge.status
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            wrapMode: Text.WordWrap
                        }
                        GlassButton {
                            visible: overlay.firstRunMode
                                && overlay.bridge.page === "ai"
                            text: "暂时跳过"
                            onClicked: {
                                if (overlay.bridge.complete_first_run()) {
                                    overlay.onboardingCompleted()
                                }
                            }
                        }
                        GlassButton {
                            visible: overlay.firstRunMode
                                && overlay.bridge.page === "provider"
                            enabled: overlay.bridge.provider_configured
                            text: overlay.bridge.provider_configured
                                ? "配置 AI" : "请先完成供应商质检"
                            primary: overlay.bridge.provider_configured
                            onClicked: overlay.bridge.select_page("ai")
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: futuOpenDGuideDialog
        objectName: "futuOpenDGuideDialog"
        anchors.fill: parent
        z: 40
        visible: overlay.futuGuideOpen
        opacity: visible ? 1 : 0
        color: Theme.modalScrim

        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        MouseArea { anchors.fill: parent }

        GlassPanel {
            id: futuGuidePanel
            width: Math.min(660, parent.width - 40)
            height: Math.min(430, parent.height - 40)
            anchors.centerIn: parent
            color: Theme.dark ? "#FF20242A" : "#FFF8F7F4"
            scale: futuOpenDGuideDialog.visible ? 1 : 0.98

            Behavior on scale {
                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        spacing: 3
                        Text {
                            text: "使用富途前，需要本机 OpenD"
                            color: Theme.text
                            font.pixelSize: 21
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "OpenD 是富途官方桌面网关；EquityLens 只与它建立本机只读连接。"
                            color: Theme.secondaryText
                            font.pixelSize: 11
                        }
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "关闭"
                        onClicked: overlay.futuGuideOpen = false
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 112
                    spacing: 0

                    Repeater {
                        model: [
                            {"number": "1", "title": "安装 OpenD",
                                "detail": "使用官方安装包"},
                            {"number": "2", "title": "登录富途",
                                "detail": "在 OpenD 内完成"},
                            {"number": "3", "title": "本机质检",
                                "detail": "连接 127.0.0.1"},
                            {"number": "4", "title": "启用供应商",
                                "detail": "通过后再切换"}
                        ]
                        delegate: RowLayout {
                            id: futuSequenceStep
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            spacing: 0

                            ColumnLayout {
                                Layout.preferredWidth: 116
                                spacing: 6
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    Layout.preferredWidth: 34
                                    Layout.preferredHeight: 34
                                    radius: 17
                                    color: Theme.accentSoft
                                    Text {
                                        anchors.centerIn: parent
                                        text: futuSequenceStep
                                            .modelData.number
                                        color: Theme.accent
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: futuSequenceStep.modelData.title
                                    horizontalAlignment: Text.AlignHCenter
                                    color: Theme.text
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: futuSequenceStep.modelData.detail
                                    horizontalAlignment: Text.AlignHCenter
                                    color: Theme.secondaryText
                                    font.pixelSize: 9
                                }
                            }
                            Rectangle {
                                visible: futuSequenceStep.index < 3
                                Layout.fillWidth: true
                                Layout.preferredHeight: 1
                                Layout.alignment: Qt.AlignVCenter
                                color: Theme.hairline
                            }
                        }
                    }
                }

                GlassPanel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 112

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 7
                        Text {
                            text: "软件负责到哪里"
                            color: Theme.text
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "我们检查 OpenD 是否安装并运行、行情是否已登录，以及 AAPL 的资料、快照、日线和历史额度是否可用。账号和登录状态由 OpenD 管理；软件不接入交易，也不会索取资产、持仓、订单或下单权限。"
                            color: Theme.secondaryText
                            font.pixelSize: 10
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    GlassButton {
                        id: futuDownloadButton
                        objectName: "futuDownloadButton"
                        text: "下载与安装说明  ↗"
                        onClicked: overlay.bridge.open_futu_download()
                    }
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "打开 OpenD"
                        onClicked: overlay.bridge.open_futu_opend()
                    }
                    GlassButton {
                        text: "我已登录，开始质检"
                        primary: true
                        enabled: !overlay.bridge.busy
                        onClicked: {
                            overlay.futuGuideOpen = false
                            overlay.bridge.quality_provider()
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !overlay.firstRunMode && overlay.bridge.reset_pending
        color: Theme.dark ? "#B0000000" : "#70323842"

        GlassPanel {
            width: 460
            height: 260
            anchors.centerIn: parent

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 22
                spacing: 12

                Text {
                    text: "恢复默认"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.Bold
                }
                Text {
                    Layout.fillWidth: true
                    text: "将永久清除本机数据：" + overlay.bridge.reset_summary
                        + "。请输入“恢复默认”进行第二次确认。"
                    color: Theme.secondaryText
                    wrapMode: Text.WordWrap
                }
                GlassTextInput {
                    id: resetConfirmation
                    Layout.fillWidth: true
                    placeholderText: "恢复默认"
                }
                RowLayout {
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        onClicked: overlay.bridge.cancel_reset()
                    }
                    GlassButton {
                        text: "清空并重启"
                        primary: true
                        onClicked: overlay.bridge.confirm_reset(
                            resetConfirmation.text)
                    }
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !overlay.firstRunMode
            && overlay.bridge.diagnostic_clear_pending
        color: Theme.dark ? "#B0000000" : "#70323842"

        GlassPanel {
            width: 440
            height: 230
            anchors.centerIn: parent

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 22
                spacing: 12

                Text {
                    text: "清空诊断日志"
                    color: Theme.text
                    font.pixelSize: 20
                    font.weight: Font.Bold
                }
                Text {
                    Layout.fillWidth: true
                    text: "将删除当前本机诊断记录。请输入“清空日志”进行第二次确认。"
                    color: Theme.secondaryText
                    wrapMode: Text.WordWrap
                }
                GlassTextInput {
                    id: diagnosticClearConfirmation
                    Layout.fillWidth: true
                    placeholderText: "清空日志"
                }
                RowLayout {
                    Item { Layout.fillWidth: true }
                    GlassButton {
                        text: "取消"
                        onClicked: {
                            diagnosticClearConfirmation.clear()
                            overlay.bridge
                                .cancel_clear_diagnostics()
                        }
                    }
                    GlassButton {
                        text: "确认清空"
                        primary: true
                        onClicked: {
                            if (overlay.bridge
                                    .confirm_clear_diagnostics(
                                        diagnosticClearConfirmation
                                            .text)) {
                                diagnosticClearConfirmation.clear()
                            }
                        }
                    }
                }
            }
        }
    }
}
