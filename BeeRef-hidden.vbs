Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & scriptDir & "\BeeRef-hidden.cmd" & Chr(34)
For Each argument In WScript.Arguments
    command = command & " " & Chr(34) & _
        Replace(argument, Chr(34), Chr(34) & Chr(34)) & Chr(34)
Next
shell.Run command, 0, False
