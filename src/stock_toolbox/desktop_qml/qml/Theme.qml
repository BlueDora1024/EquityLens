pragma Singleton
import QtQuick

QtObject {
    property bool dark: false

    readonly property int sidebarWidth: 220
    readonly property int controlHeight: 40
    readonly property int panelRadius: 21
    readonly property int controlRadius: 13

    readonly property color text: dark ? "#EEF1F5" : "#19202A"
    readonly property color secondaryText: dark ? "#8E949F" : "#7B818A"
    readonly property color faintText: dark ? "#6F7580" : "#9A9FA6"
    readonly property color window: dark ? "#F2181B20" : "#EDEBE8E3"
    readonly property color titlebar: dark ? "#E91C1F25" : "#E9F5F4F1"
    readonly property color sidebar: dark ? "#C920242A" : "#B8F5F7F8"
    readonly property color panel: dark ? "#B82A2E35" : "#B8FFFFFF"
    readonly property color overlayPanel: dark ? "#F021242A" : "#FFF8F7F4"
    readonly property color field: dark ? "#8C181A1F" : "#B8FFFFFF"
    readonly property color hairline: dark ? "#17FFFFFF" : "#66FFFFFF"
    readonly property color accent: dark ? "#7186CA" : "#5369A8"
    readonly property color accentSoft: dark ? "#38798BC9" : "#2E5369A8"
    readonly property color warning: dark ? "#D9B36C" : "#9A6D25"
    readonly property color warningSoft: dark ? "#2ED5A03E" : "#22D99D38"
    readonly property color success: dark ? "#82D9AE" : "#2F8A5D"
    readonly property color successSoft: dark ? "#2440B77B" : "#1C3DBE7E"
    readonly property color dangerSoft: dark ? "#2EE66B70" : "#1FE35D67"
    readonly property color danger: dark ? "#E18C86" : "#A9534E"
    readonly property color shadow: dark ? "#52000000" : "#162D3440"
    readonly property color warmGlow: dark ? "#182A2030" : "#3DFFE4D7"
    readonly property color coolGlow: dark ? "#1C30405B" : "#4DC4D9EA"
    readonly property color modalScrim: dark ? "#A6000000" : "#66323842"
}
