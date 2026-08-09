import QtQuick
import QtQuick.Controls
import ".."

TextField {
    id: control

    property bool secret: false

    implicitHeight: Theme.controlHeight
    leftPadding: 13
    rightPadding: 13
    color: Theme.text
    placeholderTextColor: Theme.faintText
    selectionColor: Theme.accent
    selectedTextColor: "#FFFFFF"
    echoMode: secret ? TextInput.Password : TextInput.Normal
    font.pixelSize: 13

    background: Rectangle {
        radius: Theme.controlRadius
        color: control.hovered ? Theme.accentSoft : Theme.field
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : Theme.hairline
    }
}
