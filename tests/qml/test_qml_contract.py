from __future__ import annotations

from pathlib import Path

_QML_ROOT = Path("src/stock_toolbox/desktop_qml/qml")


def qml_text(relative: str) -> str:
    return (_QML_ROOT / relative).read_text(encoding="utf-8")


def test_soft_glass_tokens_match_frozen_b_contract() -> None:
    theme = qml_text("Theme.qml")

    assert "readonly property int sidebarWidth: 220" in theme
    assert "readonly property int controlHeight: 40" in theme
    assert "readonly property int panelRadius: 21" in theme
    assert "readonly property int controlRadius: 13" in theme


def test_interactive_components_paint_their_own_backgrounds() -> None:
    for name in ("GlassButton.qml", "GlassField.qml", "ChoiceChip.qml"):
        source = qml_text(f"components/{name}")
        assert "background:" in source
        assert "Theme." in source


def test_glass_field_keeps_cached_options_visible_while_refreshing() -> None:
    source = qml_text("components/GlassField.qml")

    assert "visible: control.count > 0" in source
    assert "visible: control.loading && control.count === 0" in source


def test_glass_panels_do_not_render_through_offscreen_texture_layers() -> None:
    panel = qml_text("components/GlassPanel.qml")

    assert "layer.enabled" not in panel


def test_shared_controls_use_one_height_and_explicit_centering_contract() -> None:
    button = qml_text("components/GlassButton.qml")
    sidebar = qml_text("components/SidebarItem.qml")

    assert "implicitHeight: Theme.controlHeight" in button
    assert "width: control.availableWidth" in button
    assert "height: control.availableHeight" in button
    assert "horizontalAlignment: Text.AlignHCenter" in button
    assert "verticalAlignment: Text.AlignVCenter" in button
    assert "height: control.availableHeight" in sidebar


def test_shared_controls_use_restrained_pointer_feedback() -> None:
    button = qml_text("components/GlassButton.qml")
    info_tip = qml_text("components/InfoTip.qml")

    assert "scale: control.down ? 0.985 : 1" in button
    assert "Behavior on scale" in button
    assert "duration: 120" in button
    assert "delay: 180" in info_tip


def test_shared_button_owns_centered_busy_indicator() -> None:
    button = qml_text("components/GlassButton.qml")
    importer = qml_text("ImportOverlay.qml")

    assert "property bool busy: false" in button
    assert "BusySpinner" in button
    assert "anchors.centerIn: parent" in button
    assert "busy: overlay.importLaunchPending" in importer
    assert "BusySpinner {" not in importer


def test_ai_connection_actions_stay_inside_the_connection_panel() -> None:
    source = qml_text("SettingsOverlay.qml")

    assert 'objectName: "aiConnectionPanel"' in source
    assert 'objectName: "aiConnectionActions"' in source
    assert "Layout.preferredHeight: 214" in source
    assert 'busy: overlay.bridge.busy_action === "ai_setup"' in source


def test_settings_workspace_explains_provider_and_ai_boundaries() -> None:
    source = qml_text("SettingsOverlay.qml")

    for copy in (
        "我已完成授权，开始自检",
        "官方 SDK",
        "不申请账户资产、资金明细、订单查询或下单权限",
        "接入新供应商",
        "自动检测并配置",
        "最多三个全局分类",
        "不设置 AI",
        "外观",
        "跟随系统",
        "浅色",
        "深色",
    ):
        assert copy in source


def test_futu_settings_has_opend_sequence_and_atomic_activation_controls() -> None:
    source = qml_text("SettingsOverlay.qml")

    for required in (
        'objectName: "futuProviderPanel"',
        'objectName: "futuOpenDGuideDialog"',
        'objectName: "futuOpenButton"',
        'objectName: "futuQualityButton"',
        'objectName: "futuActivateButton"',
        'objectName: "futuDownloadButton"',
        "本机 Futu OpenD",
        "不接入交易",
        "activate_selected_provider()",
    ):
        assert required in source


def test_longbridge_settings_can_switch_back_from_another_provider() -> None:
    source = qml_text("SettingsOverlay.qml")
    compact = "".join(source.split())

    assert 'objectName: "longbridgeActivateButton"' in source
    assert 'overlay.bridge.active_provider_id!=="longbridge"' in compact


def test_analysis_and_fallback_surfaces_use_active_provider_copy() -> None:
    rs = qml_text("RsRunPage.qml")
    fallback = qml_text("components/FallbackConfirmOverlay.qml")
    master = qml_text("MasterDataPage.qml")
    importer = qml_text("ImportOverlay.qml")

    assert "rsRunBridge.provider_status" in rs
    assert "行情服务暂时不可用" in fallback
    assert "从第一步重新计算" in fallback
    assert "前往网络设置" in fallback
    assert "供应商暂未提供公司简介" in master
    assert "由供应商资料保底" in importer


def test_settings_overlay_configures_display_timezone_and_proxy() -> None:
    source = qml_text("SettingsOverlay.qml")

    for copy in (
        "日期与时间",
        "北京时间",
        "美东时间",
        "跟随系统时区",
        "网络与备用行情",
        "跟随系统代理",
        "自定义代理",
        "检查网络代理",
        "检查 Yahoo 备用行情",
    ):
        assert copy in source
    assert 'objectName: "proxyUrlInput"' in source
    assert 'objectName: "proxyQualityButton"' in source
    assert "save_network(" in source
    assert "quality_proxy()" in source


def test_first_run_workspace_does_not_leave_a_large_modal_gutter() -> None:
    window = qml_text("PilotWindow.qml")
    settings = qml_text("SettingsOverlay.qml")

    assert "anchors.margins: 0" in window
    assert "anchors.topMargin: window.firstRunRequired ? titlebar.height : 0" in window
    assert (
        "width: overlay.firstRunMode\n"
        "            ? overlay.width\n"
        "            : Math.min(1040, overlay.width - 48)" in settings
    )
    assert (
        "height: overlay.firstRunMode\n"
        "            ? overlay.height\n"
        "            : Math.min(680, overlay.height - 48)" in settings
    )


def test_product_tour_is_image_led_optional_and_persistent() -> None:
    window = qml_text("PilotWindow.qml")
    tour = qml_text("ProductTourOverlay.qml")

    for token in (
        "ProductTourOverlay",
        "productTourOpen",
        "productTourDismissed",
        "shellBridge.dismiss_product_tour()",
    ):
        assert token in window
    for copy in (
        "先建立全局证券库",
        "用标签与股票池组织计算",
        "选择一个分析工具运行",
        "在结果里复盘，不追逐预测",
        "网络异常从设置恢复",
        "不再提示",
        "下一步",
        "完成",
    ):
        assert copy in tour
    for token in (
        'objectName: "productTourOverlay"',
        'objectName: "productTourCard"',
        'objectName: "productTourIllustration"',
        "focusRing",
        "Keys.onEscapePressed",
        "Keys.onLeftPressed",
        "Keys.onRightPressed",
        "dismissForeverRequested",
    ):
        assert token in tour
    assert "请点击图中" not in tour
    assert "必须点击" not in tour


def test_product_tour_can_be_reopened_from_appearance_settings() -> None:
    window = qml_text("PilotWindow.qml")
    settings = qml_text("SettingsOverlay.qml")

    assert "signal productTourRequested" in settings
    assert 'objectName: "appearanceProductTourButton"' in settings
    assert "overlay.productTourRequested()" in settings
    assert "onProductTourRequested" in window
    assert "window.productTourOpen = true" in window


def test_product_tour_focuses_real_illustration_items_instead_of_ratios() -> None:
    tour = qml_text("ProductTourOverlay.qml")

    for target in (
        "productTourTargetSecurities",
        "productTourTargetOrganization",
        "productTourTargetAnalyses",
        "productTourTargetResults",
        "productTourTargetSettings",
    ):
        assert f'objectName: "{target}"' in tour
    assert "focusTarget" in tour
    assert "mapFromItem" in tour
    assert '"focusX"' not in tour


def test_frameless_window_controls_are_interactive() -> None:
    window = qml_text("PilotWindow.qml")

    for control in (
        '"action": "close"',
        '"action": "minimize"',
        '"action": "zoom"',
    ):
        assert control in window
    assert 'objectName: "windowControl_" + modelData.action' in window
    assert "window.close()" in window
    assert "window.showMinimized()" in window
    assert "window.showMaximized()" in window
    assert "window.showNormal()" in window


def test_settings_entry_has_keyboard_shortcut_and_tooltip() -> None:
    window = qml_text("PilotWindow.qml")
    sidebar = qml_text("components/ShellSidebar.qml")

    assert "StandardKey.Preferences" in window
    assert "window.settingsOpen = true" in window
    assert 'ToolTip.text: "设置"' in sidebar


def test_global_securities_workspace_has_managed_tags_and_safe_delete() -> None:
    source = qml_text("MasterDataPage.qml")

    for copy in (
        "displaySymbol",
        "编辑业务标签",
        "已选标签",
        "从全局标签池添加",
        "最新价",
        "总市值",
        "删除证券？",
        "确认删除",
        "security_delete_impact",
    ):
        assert copy in source
    assert "添加业务标签" not in source


def test_global_tags_workspace_has_members_and_partial_batch_addition() -> None:
    page = qml_text("MasterDataPage.qml")
    overlay = qml_text("ClassificationMemberOverlay.qml")

    for copy in (
        "标签下的证券",
        "批量添加证券",
        "classification_members",
        "select_classification",
        "classification_candidates",
        "add_classification_members",
    ):
        assert copy in page
    for copy in (
        "搜索代码或公司名称",
        "已选择",
        "已有 3 个标签，添加时会失败",
        "部分证券失败不会影响其他证券",
    ):
        assert copy in overlay


def test_rs_history_is_export_only_and_uses_csv_statistics_archive() -> None:
    source = qml_text("RsHistoryPage.qml")

    assert "导出表格" in source
    assert "RS 统计表格 ZIP (*.zip)" in source
    assert '"csv"' in source
    assert "导入历史" not in source
    assert "importDialog" not in source
    assert "import_history" not in source


def test_rs_cancel_button_disables_while_finishing_presentation() -> None:
    source = qml_text("RsRunPage.qml")

    assert "enabled: rsRunBridge.cancel_available" in source


def test_watchlist_workspace_has_two_step_batch_add_and_editable_binding() -> None:
    page = qml_text("MasterDataPage.qml")
    overlay = qml_text("WatchlistMemberOverlay.qml")

    for copy in (
        "添加证券",
        "watchlist_candidates",
        "update_watchlist_member_binding",
        "displaySymbol",
        "请先输入股票池名称",
        "createdId",
        "masterDataBridge.watchlists.find",
        "watchlistNameInput.text = name",
    ):
        assert copy in page
    for copy in (
        "选择证券",
        "调整参评标签",
        "搜索代码或公司名称",
        "下一步",
        "默认选择第一项",
        "add_watchlist_members_batch",
    ):
        assert copy in overlay
    assert "if (addedCount <= 0)" in overlay
    assert "submitError" in overlay
    assert 'objectName: "watchlistSelectAllButton"' in overlay
    assert "toggleAllVisible()" in overlay
    assert 'objectName: "watchlistCompletionButton"' in overlay
    assert "anchors.horizontalCenter: parent.horizontalCenter" in overlay
    assert "poolMember.modelData.symbol" not in page


def test_import_workspace_has_stable_empty_progress_and_result_states() -> None:
    source = qml_text("ImportOverlay.qml")

    for copy in (
        "尚未开始导入",
        "import_completed",
        "import_total",
        "import_progress",
        "ProgressBar",
        "逐项结果",
    ):
        assert copy in source
    assert "id: importProgressBar" in source
    assert "importProgressBar.visualPosition" in source
    assert "Behavior on value" in source
    assert "NumberAnimation" in source
    assert "importProgressBar.value * 100" in source
    assert "parent.parent.visualPosition" not in source
    for token in (
        "import_file_requires_choice",
        "import_file_candidates",
        "select_import_column",
        "import_preview",
        "请选择证券代码列",
        "已识别列",
    ):
        assert token in source


def test_reusable_info_tips_explain_csv_rs_and_classification_status() -> None:
    info_tip = qml_text("components/InfoTip.qml")
    importer = qml_text("ImportOverlay.qml")
    sidebar = qml_text("components/SidebarItem.qml")
    history = qml_text("RsHistoryPage.qml")

    for token in (
        "property string title",
        "property string tipText",
        "ToolTip",
        "hoverEnabled: true",
        "wrapMode: Text.Wrap",
    ):
        assert token in info_tip
    for copy in (
        'objectName: "csvFormatHelp"',
        "ticker / symbol / 股票代码",
        "UTF-8、GB18030",
        "不会猜测后直接导入",
        "AAPL.US",
    ):
        assert copy in importer
    assert "property string helpText" in sidebar
    assert "InfoTip" in sidebar
    assert '"sidebarRsHelp"' in sidebar
    assert "rowData.helpText" in qml_text("components/ShellSidebar.qml")
    assert 'objectName: "classificationStatusHelp"' in history
    assert "statusExplanation" in history


def test_rs_history_stock_projection_never_assigns_undefined_score_text() -> None:
    """Stock rows do not carry classification-only score fields."""
    history = qml_text("RsHistoryPage.qml")

    assert 'text: resultRow.modelData.scoreText || ""' in history


def test_turning_point_and_deviation_explain_how_to_read_results() -> None:
    turning = qml_text("TurningPointPage.qml")
    deviation = qml_text("ExtremeDeviationPage.qml")
    info_tip = qml_text("components/InfoTip.qml")

    for copy in (
        "短周期更灵敏但噪音更高",
        "综合分用于安排复盘优先级",
        "交易侧",
        "左侧交易 · CD",
        "右侧交易 · 均线确认",
        "位置更早、噪音更高",
        "位置更晚、确认程度更高",
        "查看未命中",
        "AI 解读",
        "matchedPeriodChips",
        "attentionScore",
    ):
        assert copy in turning
    assert "只看命中" not in turning
    assert "set_interval_selected" in turning
    assert "set_trade_side" in turning
    assert "onOpening: turningPointBridge.load_support_data()" in turning
    assert "loading: turningPointBridge.support_loading" in turning
    assert "loaded: turningPointBridge.support_loaded" in turning
    assert 'emptyText: "还没有股票池"' in turning
    assert "市值 > 20 亿美元" not in turning
    assert "250 日收益为正" not in turning
    assert "风险标注" in turning
    assert "riskLabels" in turning
    assert "小市值" in turning
    assert "长期趋势偏弱" not in turning
    assert "长期样本不足" not in turning
    assert 'objectName: "turningLeftHelp"' in turning
    assert 'objectName: "turningRightHelp"' in turning
    assert 'objectName: "turningLeftChoice"' in turning
    assert 'objectName: "turningRightChoice"' in turning
    assert 'objectName: "turningInlineUnmatchedList"' in turning
    assert "turningPointBridge.matched_count === 0" in turning
    assert "lightSurface: true" in turning
    assert 'root.lightSurface ? "#182230" : Theme.text' in info_tip
    assert 'root.lightSurface ? "#667085" : Theme.secondaryText' in info_tip
    assert "signalLabels\n                                                .join" not in turning
    assert "matchedPeriodChips" in turning
    assert "result_empty_text" in turning
    assert "负分偏买入观察" in deviation
    assert "绝对值越大" in deviation


def test_choice_chip_has_unmistakable_selected_state() -> None:
    chip = qml_text("components/ChoiceChip.qml")

    assert "control.checked ? Theme.accentSoft : Theme.field" in chip
    assert "control.checked ? Theme.accent : Theme.hairline" in chip
    assert "control.checked ? Font.DemiBold : Font.Normal" in chip


def test_turning_run_and_history_are_separate_record_scoped_surfaces() -> None:
    turning = qml_text("TurningPointPage.qml")

    for copy in (
        'objectName: "turningRunSurface"',
        'objectName: "turningRunConsole"',
        'objectName: "turningHistorySurface"',
        'text: "股票池与日期"',
        'text: "策略与周期"',
        'text: busy ? "计算中" : "开始计算"',
        'text: "记录结果 · "',
        'objectName: "turningHistoryResultFilters"',
        "text: turningPointBridge.selected_run_pinned",
        "turningPointBridge.selected_run_id",
        ".selectedPeriod.signalAt",
        "resultRow.modelData.selectedPeriod.crossedAt",
        "resultRow.modelData.selectedPeriod.enhancedAt",
    ):
        assert copy in turning
    assert "综合关注结果" not in turning
    assert "全部命中" not in turning
    assert 'text: "新建筛选"' not in turning
    assert "RsAIReportOverlay" in turning
    assert "reportDialogOpen" in turning
    assert "turningPointBridge.matched_count > 0" in turning
    assert 'nameFilters: ["拐点筛选表格 (*.csv)"]' in turning
    assert "exportDialog.currentFile = turningPointBridge.export_default_url" in turning


def test_turning_history_keeps_result_period_filters_inside_detail_panel() -> None:
    turning = qml_text("TurningPointPage.qml")

    assert 'objectName: "turningHistoryResultFilters"' in turning
    assert turning.index('objectName: "turningHistorySurface"') < turning.index(
        'objectName: "turningHistoryResultFilters"'
    )
    assert "historyRow.modelData.completedAt" in turning


def test_turning_history_uses_a_true_empty_state_without_record_actions() -> None:
    turning = qml_text("TurningPointPage.qml")

    assert 'objectName: "turningHistoryEmptyState"' in turning
    assert 'objectName: "turningHistoryRecordContent"' in turning
    assert "visible: page.hasSelectedHistory" in turning
    assert "visible: !page.hasSelectedHistory" in turning
    assert 'text: "暂无拐点筛选记录"' in turning
    assert 'text: "完成一次拐点筛选后，结果会显示在这里。"' in turning


def test_analysis_reports_keep_old_content_visible_with_error_feedback() -> None:
    turning = qml_text("TurningPointPage.qml")
    extreme = qml_text("ExtremeDetailView.qml")

    assert "RsAIReportOverlay" in turning
    assert "errorText: page.reportErrorText" in turning
    assert "reportText: turningPointBridge.report_text" in turning
    assert "page.reportErrorText.length > 0" in turning
    assert 'objectName: "extremeReportDialog"' in extreme
    assert "reportText: extremeDeviationBridge.report_text" in extreme
    assert "errorText: view.reportErrorText" in extreme
    assert "重新分析" in extreme
    assert "regenerateEnabled: extremeDeviationBridge.ai_configured" in extreme


def test_dense_analysis_results_remain_readable_at_standard_width() -> None:
    turning = qml_text("TurningPointPage.qml")
    extreme_results = qml_text("ExtremeResultsView.qml")
    extreme_run = qml_text("ExtremeRunView.qml")
    extreme_detail = qml_text("ExtremeDetailView.qml")
    theme = qml_text("Theme.qml")

    assert "Flow {" in turning
    assert "GridView {" in turning
    assert "readonly property bool compactHeight: height < 720" in turning
    assert "visible: !page.historyMode && turningPointBridge.running" in turning
    assert 'return parts.join("\\n")' in turning
    assert "maximumLineCount: 3" in turning
    assert "modalScrim" in theme
    assert "extremeDeviationBridge.result_history" in extreme_results
    assert "AI 解读所选" not in extreme_results
    for source in (extreme_results, extreme_run, extreme_detail):
        assert "function displaySymbol" in source
        assert r'replace(/\.US$/, "")' in source


def test_deviation_chart_labels_visible_price_extrema() -> None:
    chart = qml_text("components/DeviationChart.qml")

    assert "最高" in chart
    assert "最低" in chart
    assert 'drawPriceGuide("最高", high)' in chart
    assert 'drawPriceGuide("最低", low)' in chart


def test_deviation_chart_uses_original_pressure_with_visual_contrast() -> None:
    chart = qml_text("components/DeviationChart.qml")

    assert "buyVisualStrength" in chart
    assert "sellVisualStrength" in chart
    assert "buyPressure" in chart
    assert "sellPressure" in chart
    assert "原始买卖压力" in chart


def test_extreme_result_history_does_not_repeat_a_matching_company_code() -> None:
    source = qml_text("ExtremeResultsView.qml")

    assert "function securityTitle" in source
    assert "name.toUpperCase() === code.toUpperCase()" in source
    assert "view.securityTitle(" in source


def test_extreme_period_rows_explain_scores_without_a_vague_evidence_toggle() -> None:
    source = qml_text("ExtremeDetailView.qml")

    assert "function periodExplanation" in source
    assert "InfoTip" in source
    assert "scoreColumnWidth" in source
    assert "buyDeviationColumnWidth" in source
    assert "Theme.success" in source
    assert "Theme.danger" in source
    assert "查看计算依据" not in source


def test_extreme_run_uses_one_security_and_shared_date_picker() -> None:
    source = qml_text("ExtremeRunView.qml")

    assert "DatePickerField {" in source
    assert 'objectName: "extremeEndDatePicker"' in source
    assert "load_support_data()" in source
    assert "member_count" in source
    assert "calendar_loading" in source
    assert "BusySpinner" in source
    assert "set_symbol_selected" not in source
    assert "set_all_symbols" not in source
    assert "只请求已选周期" in source
    assert "selected_security_id" in source
    assert "SearchablePicker" in source
    assert "set_interval_selected" in source
    assert 'objectName: "extremeSecurityPicker"' in source
    assert source.count("Layout.preferredHeight: 54") >= 2


def test_extreme_progress_panel_stays_compact_in_idle_and_running_states() -> None:
    source = qml_text("ExtremeRunView.qml")

    assert 'objectName: "extremeProgressPanel"' in source
    assert "Layout.fillHeight: false" in source
    assert "Layout.preferredHeight: view.showLiveStatus ? 220 : 72" in source
    assert "Layout.maximumHeight: view.showLiveStatus ? 220 : 72" in source
    assert 'objectName: "extremeIdleSpacer"' in source
    assert "Layout.fillHeight: true" in source
    assert "visible: !view.showLiveStatus" not in source


def test_extreme_page_resets_prior_result_state_when_run_surface_opens() -> None:
    source = qml_text("ExtremeDeviationPage.qml")
    sidebar = qml_text("components/ShellSidebar.qml")

    assert "extremeDeviationBridge.prepare_new_run()" in source
    assert "onResultsModeChanged" in source
    assert "onVisibleChanged" in source
    assert 'rowData.pageId === "extreme_deviation.run"' in sidebar
    assert "extremeDeviationBridge.prepare_new_run()" in sidebar


def test_analysis_runs_share_resource_budget_preflight_and_confirmation() -> None:
    card = qml_text("components/ResourceBudgetCard.qml")
    overlay = qml_text("components/BudgetConfirmOverlay.qml")

    for token in (
        "预计任务",
        "缓存命中",
        "预计外部请求",
        "数据路径",
        "最多四路并发",
        "quotaNotice",
    ):
        assert token in card
    for token in (
        "确认本次资源消耗",
        "不会修改股票池、周期或日期",
        "继续运行",
        "返回调整",
        "confirmRequested",
        "dismissRequested",
        "futuSerialNotice",
        "改用 Yahoo",
        "继续使用富途",
        "yahooRequested",
    ):
        assert token in overlay

    pages = {
        "RsRunPage.qml": "rsRunBridge",
        "TurningPointPage.qml": "turningPointBridge",
        "ExtremeRunView.qml": "extremeDeviationBridge",
    }
    for path, bridge in pages.items():
        source = qml_text(path)
        if path != "ExtremeRunView.qml":
            assert "ResourceBudgetCard {" in source
        assert "BudgetConfirmOverlay {" in source
        if path != "ExtremeRunView.qml":
            assert f"loading: {bridge}.budget_loading" in source
        assert f"coldRequests: {bridge}.estimated_cold_requests" in source
        assert f"quotaNotice: {bridge}.quota_notice" in source
        assert f"quotaRemaining: {bridge}.quota_remaining" in source
        assert f"quotaNewSymbols: {bridge}.quota_new_symbols" in source
        assert f"quotaShortfall: {bridge}.quota_shortfall" in source
        assert f"futuSerialNotice: {bridge}.futu_serial_notice" in source
        assert f"{bridge}.use_yahoo_for_budget_and_start()" in source
        assert f"visible: {bridge}.requires_budget_confirmation" in source
        assert f"{bridge}.confirm_budget_and_start()" in source
        assert f"{bridge}.dismiss_budget_confirmation()" in source


def test_budget_overlay_has_a_dedicated_futu_quota_shortfall_decision() -> None:
    source = qml_text("components/BudgetConfirmOverlay.qml")

    for token in (
        'objectName: "budgetConfirmOverlay"',
        "property int quotaRemaining: -1",
        "property int quotaNewSymbols: -1",
        "property int quotaShortfall: 0",
        "readonly property bool quotaBlocked: quotaShortfall > 0",
        '"富途历史额度不足"',
        '"本次使用 Yahoo"',
        "visible: !overlay.quotaBlocked",
    ):
        assert token in source
    assert source.count("color: Theme.modalScrim") == 1
    assert source.count("GlassPanel {") == 1


def test_first_run_gates_ai_until_provider_quality_and_uses_clear_copy() -> None:
    source = qml_text("SettingsOverlay.qml")
    window = qml_text("PilotWindow.qml")

    assert (
        "enabled: !overlay.firstRunMode\n"
        "                            || overlay.bridge.provider_configured" in source
    )
    assert "请先完成供应商质检" in source
    assert '? "配置 AI" : "请先完成供应商质检"' in source
    assert "width: aiSettingsPage.width" in source
    assert "&& overlay.bridge.complete_first_run()" in source
    assert 'shellBridge.navigate("securities")' in window


def test_global_securities_refresh_requires_confirmation_and_shows_progress() -> None:
    source = qml_text("MasterDataPage.qml")

    for token in (
        'objectName: "globalRefreshButton"',
        'objectName: "globalRefreshConfirmOverlay"',
        'objectName: "globalRefreshConfirmButton"',
        'objectName: "globalRefreshProgress"',
        "masterDataBridge.refresh_securities()",
        "masterDataBridge.refresh_running",
        "masterDataBridge.refresh_progress",
    ):
        assert token in source


def test_rs_run_uses_real_date_pickers_and_no_hard_coded_custom_dates() -> None:
    source = qml_text("RsRunPage.qml")
    picker = qml_text("components/DatePickerField.qml")

    for token in (
        'objectName: "rsWatchlistField"',
        "rsRunBridge.load_watchlists()",
        "rsRunBridge.watchlists_loading",
        'objectName: "rsEndDatePicker"',
        'objectName: "rsCustomStartPicker"',
        'objectName: "rsCustomEndPicker"',
        "rsRunBridge.set_custom_enabled(checked)",
        "rsRunBridge.set_custom_dates(",
    ):
        assert token in source
    assert '"2026-04-24", "2026-07-24"' not in source
    assert source.count("openAbove: true") == 2
    assert source.count("maximumDate: rsRunBridge.maximum_historical_date") == 3
    for token in ("Popup", "GridLayout", "dateSelected", "上一月", "下一月"):
        assert token in picker
    assert "property string maximumDate" in picker
    assert "cellAllowed" in picker


def test_rs_run_shows_honest_live_progress_and_locks_configuration() -> None:
    source = qml_text("RsRunPage.qml")

    for token in (
        'objectName: "rsRunOutcomeCard"',
        "RunOutcomeCard {",
        "rsRunBridge.stage_label",
        "rsRunBridge.stage_detail",
        "rsRunBridge.failed_count",
        "rsRunBridge.terminal_visible",
        "rsRunBridge.progress",
        "enabled: !rsRunBridge.running",
        '"重新运行" : "开始运行"',
        "readonly property bool compactHeight: height < 720",
        "visible: !page.showLiveStatus && !page.compactHeight",
    ):
        assert token in source
    assert 'rsRunBridge.preflight_ready ? "已通过预检"' in source


def test_rs_history_separates_ranges_and_gates_saved_ai_report() -> None:
    history = qml_text("RsHistoryPage.qml")
    report_overlay = qml_text("RsAIReportOverlay.qml")
    run = qml_text("RsRunPage.qml")

    for token in (
        "rsHistoryBridge.ranges",
        "rsHistoryBridge.selected_range_id",
        "rsHistoryBridge.select_range",
        "rsHistoryBridge.ai_configured",
        "rsHistoryBridge.report_running",
        "rsHistoryBridge.report_text",
        "rsHistoryBridge.report_error",
        "rsHistoryBridge.generate_report()",
        "AI 强弱解读",
        "AI 尚未配置",
        "前往设置",
        "shellBridge.open_settings()",
        "AI 正在整理强弱证据",
        "个股收益",
        "当前参评分类",
        'objectName: "rsAIReportCard"',
        "Layout.preferredHeight: 88",
        "reportDialogOpen",
        "查看 AI 解读",
        "scoreText",
        "statusHelpVisible",
        "exportDialog.currentFile = rsHistoryBridge.export_default_url",
        'nameFilters: ["RS 统计表格 ZIP (*.zip)"]',
        'defaultSuffix: "zip"',
    ):
        assert token in history
    for token in (
        'objectName: "rsAIReportOverlay"',
        'objectName: "rsAIReportPanel"',
        'objectName: "rsAIReportCloseButton"',
        "重新生成",
        "ScrollBar.vertical",
        "closeRequested",
        "regenerateRequested",
    ):
        assert token in report_overlay
    assert "Layout.preferredHeight: 190" not in history
    assert "重新运行" not in history
    assert "重新运行" in run


def test_rs_pages_teach_reading_and_keep_one_sortable_benchmark_summary() -> None:
    run = qml_text("RsRunPage.qml")
    history = qml_text("RsHistoryPage.qml")

    for token in (
        'objectName: "rsReadingGuide"',
        "怎么阅读",
        "RS > 0",
        "跑赢基准",
        "分类综合",
        "周期分歧",
        "不预测未来",
    ):
        assert token in run
    for token in (
        "rsHistoryBridge.selected_range_summary",
        "rsHistoryBridge.stock_sort_descending",
        "rsHistoryBridge.toggle_stock_sort()",
        "强 → 弱",
        "弱 → 强",
    ):
        assert token in history
    assert history.count("benchmarkReturn") == 1
    assert history.count("基准收益") == 1
    assert "tipText: page.showClassifications" in history
    assert "text: page.showClassifications" in history


def test_analysis_pages_share_one_outcome_and_failure_detail_contract() -> None:
    pages = {
        "RsRunPage.qml": ("rsRunBridge", "failed_count"),
        "TurningPointPage.qml": ("turningPointBridge", "failure_count"),
        "ExtremeRunView.qml": ("extremeDeviationBridge", "failure_count"),
    }

    for path, (bridge, failure_count) in pages.items():
        source = qml_text(path)
        assert source.count("RunOutcomeCard {") == 1
        assert source.count("FailureDetailOverlay {") == 1
        for binding in (
            f"running: {bridge}.running",
            f"recoveryVisible: {bridge}.recovery_visible",
            f"recoveryTone: {bridge}.recovery_tone",
            f"recoveryMessage: {bridge}.recovery_message",
            f"retryCount: {bridge}.retry_count",
            f"waitSeconds: {bridge}.wait_seconds",
            f"activeConcurrency: {bridge}.active_concurrency",
            f"outcomeVisible: {bridge}.outcome_visible",
            f"outcomeTone: {bridge}.outcome_tone",
            f"outcomeTitle: {bridge}.outcome_title",
            f"outcomeSummary: {bridge}.outcome_summary",
            f"primaryAction: {bridge}.outcome_primary_action",
            f"primaryLabel: {bridge}.outcome_primary_label",
            f"failureCount: {bridge}.{failure_count}",
        ):
            assert binding in source
        assert f"openWithSnapshot({bridge}.failure_groups)" in source
        assert f"{bridge}.start()" in source
        assert "shellBridge.open_settings()" in source


def test_rs_quota_outcome_keeps_an_explicit_restart_action() -> None:
    source = qml_text("RsRunPage.qml")

    assert 'text: rsRunBridge.outcome_visible ? "重新运行" : "开始运行"' in source
    assert (
        'visible: !rsRunBridge.outcome_visible\n'
        '                            || rsRunBridge.outcome_primary_action !== "retry"'
    ) in source


def test_run_outcome_card_is_restrained_and_has_no_dead_action_kind() -> None:
    source = qml_text("components/RunOutcomeCard.qml")

    for token in (
        "property bool running",
        "property bool recoveryVisible",
        "property bool outcomeVisible",
        "property string primaryAction",
        "signal primaryActionRequested",
        "signal detailsRequested",
        "已降为 1 路请求",
        "Theme.warning",
        "Theme.success",
        "Theme.danger",
        "GlassButton {",
        "readonly property bool stackActions",
        "implicitHeight: present ? contentGrid.implicitHeight + 24 : 0",
        'objectName: "outcomeDetailsButton"',
        'objectName: "outcomePrimaryButton"',
    ):
        assert token in source
    button = qml_text("components/GlassButton.qml")
    assert "horizontalAlignment: Text.AlignHCenter" in button
    assert "verticalAlignment: Text.AlignVCenter" in button
    assert 'primaryAction === "retry"' in source
    assert 'primaryAction === "open_settings"' in source
    # Task 5 exposes no clear-cache handler, so that action is deliberately
    # omitted instead of rendering a button that cannot perform work.
    assert "clear_cache" not in source
    assert "SequentialAnimation" not in source
    assert "loops: Animation.Infinite" not in source


def test_failure_detail_is_explicit_modal_snapshot_not_a_live_binding() -> None:
    source = qml_text("components/FailureDetailOverlay.qml")

    for token in (
        'objectName: "failureDetailOverlay"',
        "function openWithSnapshot(groups)",
        "snapshotModel",
        "MouseArea",
        "onWheel:",
        "Keys.onEscapePressed",
        "closeRequested",
        "symbols",
        "intervals",
        "expandedCodes",
        "FocusScope",
        "Accessible.role: Accessible.Dialog",
        'Accessible.name: "失败详情"',
        "activeFocusOnTab: true",
        "Keys.onReturnPressed",
        "Keys.onEnterPressed",
        "Keys.onSpacePressed",
        "TextEdit {",
        "selectByMouse: true",
        "wrapMode: TextEdit.Wrap",
    ):
        assert token in source
    assert "model: overlay.snapshotModel" in source
    assert "bridge.failure_groups" not in source
    assert "Connections {" not in source
    assert "exception" not in source.lower()
    assert "sql" not in source.lower()
    assert "height: expanded ? 106 : 52" not in source
    assert "maximumLineCount: 2" not in source
    assert "elide: Text.ElideRight" not in source


def test_active_close_guard_reuses_one_confirmation_and_waits_for_terminal() -> None:
    source = qml_text("PilotWindow.qml")

    for token in (
        "onClosing:",
        "shellBridge.has_active_operation",
        "window.closeGuardOpen = true",
        'objectName: "activeOperationCloseGuard"',
        "function dismissCloseGuard()",
        "function cancelAndClose()",
        "shellBridge.close_operation_admission()",
        "shellBridge.cancel_active_operation()",
        "shellBridge.reconcile_active_operation()",
        "closeAfterCancel",
        "等待",
        "取消任务并退出",
        "onActive_operation_changed",
        "Accessible.role: Accessible.Dialog",
        'Accessible.name: "任务仍在运行"',
        'objectName: "closeGuardWaitButton"',
        'objectName: "closeGuardCancelButton"',
        "Keys.onTabPressed",
        "Keys.onBacktabPressed",
    ):
        assert token in source
    assert source.count('objectName: "activeOperationCloseGuard"') == 1


def test_extreme_terminal_navigation_requires_current_usable_results() -> None:
    source = qml_text("ExtremeDeviationPage.qml")

    assert "extremeDeviationBridge.terminal_has_usable_results" in source
    assert 'shellBridge.navigate("extreme_deviation.results")' in source
    assert 'shellBridge.navigate("extreme_deviation.run")' in source
    finished_handler = source.split("function onFinished(): void {", 1)[1].split(
        "function onReport_finished(): void {",
        1,
    )[0]
    assert "extremeDeviationBridge.results.length" not in finished_handler


def test_extreme_results_are_the_only_history_surface() -> None:
    page = qml_text("ExtremeDeviationPage.qml")
    results = qml_text("ExtremeResultsView.qml")
    detail = qml_text("ExtremeDetailView.qml")

    assert "ExtremeHistoryView" not in page
    assert 'text: "配置"' not in page
    assert 'text: "个股结论"' not in page
    assert "result_history" in results
    assert '"置信度"' not in detail
    assert '"最后收盘"' not in detail
    assert "AI 复盘结论" not in detail


def test_advanced_settings_exposes_diagnostic_log_workspace() -> None:
    source = qml_text("SettingsOverlay.qml")

    for required in (
        'text: "诊断日志"',
        'text: "保留 7 天 · 上限 100 MB"',
        'text: "打开日志目录"',
        'text: "导出诊断包"',
        'text: "清空日志…"',
        "overlay.bridge.diagnostic_events",
        "overlay.bridge.request_clear_diagnostics()",
    ):
        assert required in source


def test_master_data_supports_confirmed_classification_unbinding_from_both_views() -> None:
    source = qml_text("MasterDataPage.qml")

    for required in (
        'objectName: "classificationUnbindConfirmOverlay"',
        "security_classification_removal_impact",
        "remove_security_classification",
        "当前参与 ",
        "后续运行按新绑定计算",
        'text: "确认移除"',
    ):
        assert required in source
    assert source.count("requestClassificationRemoval(") >= 3


def test_ai_settings_recommends_the_official_deepseek_key_flow() -> None:
    source = qml_text("SettingsOverlay.qml")
    app_source = (_QML_ROOT.parent / "app.py").read_text(encoding="utf-8")

    for required in (
        "deepseek_api_keys_url",
        "推荐先充值 10 元",
        "2–3 分钟",
        "打开 DeepSeek API Keys",
    ):
        assert required in source
    assert "settings_bridge.changed.connect(rs_run_bridge.refresh_provider_status)" in app_source


def test_import_feedback_latches_the_first_click_and_shows_activity() -> None:
    source = qml_text("ImportOverlay.qml")

    for required in (
        "property bool importLaunchPending",
        "text: overlay.importLaunchPending",
        '"正在导入…"',
        "busy: overlay.importLaunchPending",
        "onImport_finished",
    ):
        assert required in source


def test_import_editor_scrolls_and_close_actions_have_distinct_draft_semantics() -> None:
    source = qml_text("ImportOverlay.qml")

    assert 'objectName: "importTickerScroll"' in source
    assert "ScrollBar.vertical.policy: ScrollBar.AsNeeded" in source
    assert 'text: "暂时保存"' in source
    assert "function finishAndClear" in source
    assert "masterDataBridge.reset_import_session()" in source
    assert "onClicked: overlay.closeRequested()" in source


def test_update_ui_exposes_advanced_card_and_non_blocking_prompt() -> None:
    settings = qml_text("SettingsOverlay.qml")
    window = qml_text("PilotWindow.qml")
    overlay = qml_text("UpdateOverlay.qml")

    assert 'objectName: "updateSettingsPanel"' in settings
    assert "当前版本" in settings
    assert "检查更新" in settings
    assert "UpdateOverlay" in window
    assert "下载并更新" in overlay
    assert "本地证券、配置和历史记录不会被修改" in overlay
