pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "."
import "components"

ApplicationWindow {
    id: window
    objectName: "softGlassWindow"

    property string environmentLabel: ""
    property bool applicationReady: false
    property bool nativeVibrancyActive: false
    property bool firstRunRequired: false
    property bool productTourDismissed: false
    property bool productTourOpen: false
    property bool settingsOpen: firstRunRequired
    property bool importOpen: false
    property bool scenarioOpen: false
    property bool closeGuardOpen: false
    property bool closeAfterCancel: false
    // qmllint disable unqualified
    property var updater: updateBridge
    // qmllint enable unqualified
    property string closeGuardStatus: ""
    property Item closeGuardPreviousFocusItem: null
    readonly property bool modalOverlayOpen:
        settingsOpen || importOpen || scenarioOpen || closeGuardOpen
        || productTourOpen
        || window.updater.prompt_visible
        || (rsRunPage.visible && rsRunPage.modalOverlayOpen)
        || (masterDataPage.visible && masterDataPage.modalOverlayOpen)
        || (rsHistoryPage.visible && rsHistoryPage.modalOverlayOpen)
        || (turningPointPage.visible && turningPointPage.modalOverlayOpen)
        || (extremeDeviationPage.visible
            && extremeDeviationPage.modalOverlayOpen)

    function openSettingsUnlessModal(): void {
        if (!window.modalOverlayOpen) {
            window.settingsOpen = true
        }
    }

    function triggerWindowControl(action) {
        if (action === "close") {
            window.close()
        } else if (action === "minimize") {
            window.showMinimized()
        } else if (action === "zoom") {
            if (window.visibility === Window.Maximized) {
                window.showNormal()
            } else {
                window.showMaximized()
            }
        }
    }

    function dismissCloseGuard(): void {
        if (window.closeAfterCancel) {
            return
        }
        window.closeGuardOpen = false
        window.closeGuardStatus = ""
        // qmllint disable unqualified
        shellBridge.reset_operation_admission()
        // qmllint enable unqualified
    }

    function cancelAndClose(): void {
        window.closeAfterCancel = true
        window.closeGuardOpen = true
        // qmllint disable unqualified
        shellBridge.close_operation_admission()
        const accepted = shellBridge.cancel_active_operation()
        const active = shellBridge.has_active_operation
        // qmllint enable unqualified
        if (!active) {
            window.closeAfterCancel = false
            window.closeGuardOpen = false
            window.close()
            return
        }
        window.closeGuardStatus = accepted
            ? "正在安全取消；当前请求结束后会自动退出。"
            : "任务已进入安全提交阶段；完成保存后会自动退出。"
    }

    width: 1280
    height: 800
    minimumWidth: 980
    minimumHeight: 680
    visible: false
    color: nativeVibrancyActive
        ? "transparent"
        : (Theme.dark ? "#13161B" : "#E7E3DE")
    title: "EquityLens"
    flags: Qt.Window | Qt.FramelessWindowHint

    onClosing: close => {
        // qmllint disable unqualified
        const active = shellBridge.begin_operation_shutdown()
        if (active) {
            // qmllint enable unqualified
            close.accepted = false
            window.closeGuardOpen = true
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 0
        radius: window.visibility === Window.Maximized ? 0 : 25
        color: Theme.window
        border.width: 1
        border.color: Theme.hairline
        clip: true

        Rectangle {
            width: 430
            height: 430
            radius: 215
            x: 60
            y: -245
            color: Theme.coolGlow
        }

        Rectangle {
            width: 460
            height: 460
            radius: 230
            anchors.right: parent.right
            anchors.rightMargin: -170
            anchors.bottom: parent.bottom
            anchors.bottomMargin: -260
            color: Theme.warmGlow
        }

        Rectangle {
            id: titlebar
            z: 100
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 48
            color: Theme.titlebar
            border.width: 1
            border.color: Theme.hairline

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 17
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Repeater {
                    model: [
                        {"color": "#FF5F57", "action": "close"},
                        {"color": "#FEBC2E", "action": "minimize"},
                        {"color": "#28C840", "action": "zoom"}
                    ]

                    Rectangle {
                        required property var modelData
                        objectName: "windowControl_" + modelData.action
                        width: 12
                        height: 12
                        radius: 6
                        color: modelData.color
                        opacity: controlMouse.containsMouse ? 1 : 0.88

                        MouseArea {
                            id: controlMouse
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: window.triggerWindowControl(
                                parent.modelData.action)
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                text: "EquityLens"
                color: Theme.secondaryText
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            DragHandler {
                onActiveChanged: {
                    if (active) {
                        window.startSystemMove()
                    }
                }
            }
        }

        ShellSidebar {
            visible: !window.firstRunRequired
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.top: titlebar.bottom
            anchors.topMargin: 8
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
            width: Theme.sidebarWidth
        }

        Item {
            visible: !window.firstRunRequired
            anchors.left: parent.left
            anchors.leftMargin: Theme.sidebarWidth + 44
            anchors.right: parent.right
            anchors.rightMargin: 34
            anchors.top: titlebar.bottom
            anchors.topMargin: 15
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 15

            RsRunPage {
                id: rsRunPage
                anchors.fill: parent
                // qmllint disable unqualified
                visible: shellBridge.current_page === "rs_strength.run"
                // qmllint enable unqualified
                onNetworkSettingsRequested: {
                    settingsPanel.focusNetworkSection()
                    window.settingsOpen = true
                }
            }

            MasterDataPage {
                id: masterDataPage
                anchors.fill: parent
                // qmllint disable unqualified
                visible: ["securities", "classifications", "watchlists"]
                    .includes(shellBridge.current_page)
                // qmllint enable unqualified
                onImportRequested: window.importOpen = true
            }

            RsHistoryPage {
                id: rsHistoryPage
                anchors.fill: parent
                // qmllint disable unqualified
                visible: shellBridge.current_page === "rs_strength.history"
                // qmllint enable unqualified
            }

            TurningPointPage {
                id: turningPointPage
                anchors.fill: parent
                // qmllint disable unqualified
                visible: shellBridge.current_page.startsWith("turning_point.")
                // qmllint enable unqualified
                onNetworkSettingsRequested: {
                    settingsPanel.focusNetworkSection()
                    window.settingsOpen = true
                }
            }

            ExtremeDeviationPage {
                id: extremeDeviationPage
                anchors.fill: parent
                // qmllint disable unqualified
                visible: shellBridge.current_page
                    .startsWith("extreme_deviation.")
                // qmllint enable unqualified
                onNetworkSettingsRequested: {
                    settingsPanel.focusNetworkSection()
                    window.settingsOpen = true
                }
            }

            GlassPanel {
                anchors.fill: parent
                // qmllint disable unqualified
                visible: shellBridge.current_page !== "rs_strength.run"
                    && !["securities", "classifications", "watchlists"]
                        .includes(shellBridge.current_page)
                    && shellBridge.current_page !== "rs_strength.history"
                    && !shellBridge.current_page.startsWith("turning_point.")
                    && !shellBridge.current_page
                        .startsWith("extreme_deviation.")
                // qmllint enable unqualified

                Column {
                    anchors.centerIn: parent
                    spacing: 10

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        // qmllint disable unqualified
                        text: shellBridge.page_title
                        // qmllint enable unqualified
                        color: Theme.text
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "正在迁移到 Soft Glass Studio"
                        color: Theme.secondaryText
                        font.pixelSize: 12
                    }
                }
            }
        }

        Rectangle {
            visible: !window.firstRunRequired
            anchors.right: parent.right
            anchors.rightMargin: 16
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            width: studioLabel.implicitWidth + 24
            height: 32
            radius: 16
            color: Theme.field
            border.width: 1
            border.color: Theme.hairline

            Text {
                id: studioLabel
                anchors.centerIn: parent
                text: Theme.dark ? "B · Soft Glass Studio · Dark" : "B · Soft Glass Studio"
                color: Theme.secondaryText
                font.pixelSize: 10
            }
        }

        SettingsOverlay {
            id: settingsPanel
            anchors.fill: parent
            anchors.topMargin: window.firstRunRequired ? titlebar.height : 0
            visible: window.settingsOpen
            firstRunMode: window.firstRunRequired
            onCloseRequested: window.settingsOpen = false
            onOnboardingCompleted: {
                // qmllint disable unqualified
                shellBridge.navigate("securities")
                // qmllint enable unqualified
                window.firstRunRequired = false
                window.settingsOpen = false
                window.productTourOpen = !window.productTourDismissed
            }
            onScenarioRequested: {
                window.settingsOpen = false
                window.scenarioOpen = true
            }
            onProductTourRequested: {
                window.settingsOpen = false
                window.productTourOpen = true
            }
        }

        ImportOverlay {
            anchors.fill: parent
            visible: window.importOpen
            onCloseRequested: window.importOpen = false
        }

        ScenarioLabOverlay {
            anchors.fill: parent
            visible: window.scenarioOpen
            onCloseRequested: window.scenarioOpen = false
        }

        ProductTourOverlay {
            anchors.fill: parent
            visible: window.productTourOpen
            onCloseRequested: window.productTourOpen = false
            onDismissForeverRequested: {
                // qmllint disable unqualified
                if (shellBridge.dismiss_product_tour()) {
                    window.productTourDismissed = true
                }
                // qmllint enable unqualified
            }
        }

        UpdateOverlay {
            anchors.fill: parent
            visible: window.updater.prompt_visible
        }

        FocusScope {
            id: closeGuard
            objectName: "activeOperationCloseGuard"
            anchors.fill: parent
            z: 2000
            visible: window.closeGuardOpen
            opacity: visible ? 1 : 0
            Accessible.role: Accessible.Dialog
            Accessible.name: "任务仍在运行"

            function containsFocusItem(item): bool {
                let current = item
                while (current) {
                    if (current === closeGuard) {
                        return true
                    }
                    current = current.parent
                }
                return false
            }

            function moveModalFocus(forward): void {
                let candidate = window.activeFocusItem
                for (let step = 0; candidate && step < 128; ++step) {
                    candidate = candidate.nextItemInFocusChain(forward)
                    if (closeGuard.containsFocusItem(candidate)) {
                        candidate.forceActiveFocus(
                            forward
                                ? Qt.TabFocusReason : Qt.BacktabFocusReason)
                        return
                    }
                }
                closeGuardWaitButton.forceActiveFocus()
            }

            onVisibleChanged: {
                if (visible) {
                    window.closeGuardPreviousFocusItem =
                        window.activeFocusItem
                    Qt.callLater(() =>
                        closeGuardWaitButton.forceActiveFocus())
                } else if (window.closeGuardPreviousFocusItem) {
                    const restoreTarget =
                        window.closeGuardPreviousFocusItem
                    window.closeGuardPreviousFocusItem = null
                    Qt.callLater(() => restoreTarget.forceActiveFocus())
                }
            }
            Keys.onEscapePressed: window.dismissCloseGuard()
            Keys.onTabPressed: event => {
                closeGuard.moveModalFocus(true)
                event.accepted = true
            }
            Keys.onBacktabPressed: event => {
                closeGuard.moveModalFocus(false)
                event.accepted = true
            }

            Behavior on opacity {
                NumberAnimation {
                    duration: 140
                    easing.type: Easing.OutCubic
                }
            }

            Rectangle {
                anchors.fill: parent
                color: Theme.modalScrim

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onWheel: wheel => wheel.accepted = true
                }
            }

            GlassPanel {
                objectName: "activeOperationClosePanel"
                anchors.centerIn: parent
                width: Math.min(500, closeGuard.width - 40)
                height: 250
                color: Theme.overlayPanel
                scale: closeGuard.visible ? 1 : 0.985

                Behavior on scale {
                    NumberAnimation {
                        duration: 150
                        easing.type: Easing.OutCubic
                    }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 23
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.preferredWidth: 8
                            Layout.preferredHeight: 8
                            radius: 4
                            color: Theme.warning
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "任务仍在运行"
                            color: Theme.text
                            font.pixelSize: 19
                            font.weight: Font.DemiBold
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: window.closeGuardStatus
                            || "现在退出会中断当前分析。可以继续等待，"
                            + "或请求安全取消后退出。"
                        color: Theme.secondaryText
                        font.pixelSize: 11
                        lineHeight: 1.4
                        wrapMode: Text.Wrap
                    }

                    Text {
                        visible: window.closeAfterCancel
                        Layout.fillWidth: true
                        text: "不会强制中断正在进行的请求或本地事务。"
                        color: Theme.warning
                        font.pixelSize: 10
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Layout.fillWidth: true
                        Item { Layout.fillWidth: true }
                        GlassButton {
                            id: closeGuardWaitButton
                            objectName: "closeGuardWaitButton"
                            text: "等待"
                            enabled: !window.closeAfterCancel
                            Accessible.role: Accessible.Button
                            Accessible.name: "等待任务完成"
                            Keys.onTabPressed: event => {
                                closeGuardCancelButton.forceActiveFocus(
                                    Qt.TabFocusReason)
                                event.accepted = true
                            }
                            Keys.onBacktabPressed: event => {
                                closeGuardCancelButton.forceActiveFocus(
                                    Qt.BacktabFocusReason)
                                event.accepted = true
                            }
                            onClicked: window.dismissCloseGuard()
                        }
                        GlassButton {
                            id: closeGuardCancelButton
                            objectName: "closeGuardCancelButton"
                            text: window.closeAfterCancel
                                ? "正在等待安全结束…" : "取消任务并退出"
                            primary: true
                            enabled: !window.closeAfterCancel
                            Accessible.role: Accessible.Button
                            Accessible.name: text
                            Keys.onTabPressed: event => {
                                closeGuardWaitButton.forceActiveFocus(
                                    Qt.TabFocusReason)
                                event.accepted = true
                            }
                            Keys.onBacktabPressed: event => {
                                closeGuardWaitButton.forceActiveFocus(
                                    Qt.BacktabFocusReason)
                                event.accepted = true
                            }
                            onClicked: window.cancelAndClose()
                        }
                    }
                }
            }
        }
    }

    Connections {
        // qmllint disable unqualified
        target: shellBridge
        function onSettings_requested() {
            window.openSettingsUnlessModal()
        }
        function onActive_operation_changed(active: bool): void {
            if (!window.closeAfterCancel || active) {
                return
            }
            if (shellBridge.reconcile_active_operation()) {
                shellBridge.cancel_active_operation()
                return
            }
            window.closeAfterCancel = false
            window.closeGuardOpen = false
            window.close()
        }
        // qmllint enable unqualified
    }

    Shortcut {
        objectName: "preferencesShortcut"
        sequences: [StandardKey.Preferences]
        enabled: !window.modalOverlayOpen
        onActivated: window.openSettingsUnlessModal()
    }

    Timer {
        interval: 1200
        running: window.updater.startup_check_enabled
            && window.applicationReady && !window.firstRunRequired
        repeat: false
        onTriggered: window.updater.check_on_startup()
    }

    Binding {
        target: Theme
        property: "dark"
        // qmllint disable unqualified
        value: themeBridge.dark
        // qmllint enable unqualified
    }
}
