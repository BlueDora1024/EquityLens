pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: control

    property string dateValue: ""
    property string maximumDate: ""
    property string placeholderText: "选择日期"
    property bool loading: false
    property bool openAbove: false
    readonly property bool calendarOpen: calendarPopup.opened
    property int shownYear: 2000
    property int shownMonth: 0
    signal dateSelected(string value)

    implicitHeight: Theme.controlHeight

    function pad(value): string {
        return value < 10 ? "0" + value : String(value)
    }

    function parseDate(value): var {
        const parts = value.split("-")
        if (parts.length !== 3) {
            return null
        }
        const year = Number(parts[0])
        const month = Number(parts[1])
        const day = Number(parts[2])
        if (!year || month < 1 || month > 12 || day < 1 || day > 31) {
            return null
        }
        return {"year": year, "month": month - 1, "day": day}
    }

    function displayText(): string {
        const parsed = parseDate(dateValue)
        return parsed
            ? parsed.year + " 年 " + (parsed.month + 1) + " 月 "
                + parsed.day + " 日"
            : placeholderText
    }

    function openCalendar() {
        const parsed = parseDate(dateValue)
        const today = new Date()
        shownYear = parsed ? parsed.year : today.getFullYear()
        shownMonth = parsed ? parsed.month : today.getMonth()
        calendarPopup.open()
    }

    function shiftMonth(delta) {
        const shifted = new Date(shownYear, shownMonth + delta, 1, 12)
        shownYear = shifted.getFullYear()
        shownMonth = shifted.getMonth()
    }

    function dayForCell(index): int {
        const firstDay = new Date(shownYear, shownMonth, 1, 12).getDay()
        const mondayOffset = (firstDay + 6) % 7
        const day = index - mondayOffset + 1
        const days = new Date(shownYear, shownMonth + 1, 0, 12).getDate()
        return day >= 1 && day <= days ? day : 0
    }

    function selectDay(day) {
        if (!day) {
            return
        }
        const value = shownYear + "-" + pad(shownMonth + 1) + "-" + pad(day)
        if (!cellAllowed(value)) {
            return
        }
        dateSelected(value)
        calendarPopup.close()
    }

    function cellAllowed(value): bool {
        return value.length > 0
            && (!maximumDate || value <= maximumDate)
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.controlRadius
        color: fieldMouse.containsMouse ? Theme.accentSoft : Theme.field
        border.width: 1
        border.color: calendarPopup.opened ? Theme.accent : Theme.hairline

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 9
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: control.loading ? "正在获取最新交易日…" : control.displayText()
                color: control.dateValue ? Theme.text : Theme.secondaryText
                font.pixelSize: 12
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            BusyIndicator {
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
                running: control.loading
                visible: control.loading
            }
            Text {
                visible: !control.loading
                text: "日历"
                color: Theme.secondaryText
                font.pixelSize: 10
            }
        }

        MouseArea {
            id: fieldMouse
            anchors.fill: parent
            hoverEnabled: true
            enabled: control.enabled && !control.loading
            onClicked: control.openCalendar()
        }
    }

    Popup {
        id: calendarPopup
        y: control.openAbove ? -height - 6 : control.height + 6
        width: 308
        height: 340
        padding: 14
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            radius: 18
            color: Theme.dark ? "#FA2A2D33" : "#FFFBFAF7"
            border.width: 1
            border.color: Theme.hairline
        }

        contentItem: ColumnLayout {
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                GlassButton {
                    text: "上一月"
                    implicitWidth: 72
                    onClicked: control.shiftMonth(-1)
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: control.shownYear + " 年 "
                        + (control.shownMonth + 1) + " 月"
                    color: Theme.text
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Item { Layout.fillWidth: true }
                GlassButton {
                    text: "下一月"
                    implicitWidth: 72
                    onClicked: control.shiftMonth(1)
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 7
                rowSpacing: 4
                columnSpacing: 4

                Repeater {
                    model: ["一", "二", "三", "四", "五", "六", "日"]
                    Text {
                        required property string modelData
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 24
                        text: modelData
                        color: Theme.faintText
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Repeater {
                    model: 42
                    Rectangle {
                        id: dayCell
                        required property int index
                        readonly property int day: control.dayForCell(index)
                        readonly property string cellValue: day
                            ? control.shownYear + "-"
                                + control.pad(control.shownMonth + 1) + "-"
                                + control.pad(day)
                            : ""
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 32
                        radius: 10
                        color: cellValue === control.dateValue
                            ? Theme.accent
                            : (cellMouse.containsMouse
                                && control.cellAllowed(cellValue)
                                ? Theme.accentSoft : "transparent")
                        opacity: control.cellAllowed(cellValue) ? 1 : 0.32

                        Text {
                            anchors.centerIn: parent
                            text: dayCell.day ? String(dayCell.day) : ""
                            color: dayCell.cellValue === control.dateValue
                                ? "#FFFFFF" : Theme.text
                            font.pixelSize: 11
                        }
                        MouseArea {
                            id: cellMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: control.cellAllowed(dayCell.cellValue)
                            onClicked: control.selectDay(dayCell.day)
                        }
                    }
                }
            }
        }
    }
}
