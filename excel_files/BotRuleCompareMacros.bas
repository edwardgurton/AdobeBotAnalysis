Option Explicit

'==============================================================================
' Bot Rule Compare V2 - workbook maintenance macros
'
'   CleanFile      - resets the workbook ready for the next bot rule run
'   RefreshPivots  - recalculates helpers, then refreshes cache + pivots
'   SetupTab       - builds an "Instructions" tab with buttons (run once)
'
' Macro names are kept short deliberately: a Forms-control button fails with
' "Formula is too complex to be assigned to object" once (full file path) +
' (macro name) gets too long - this workbook hit that limit once already.
'
' Sheet names and ranges below were verified against the workbook's XML.
'==============================================================================

'--- Sheet names --------------------------------------------------------------
Private Const SH_FILLIN   As String = "Fill In Sheet"
Private Const SH_SEGLIST  As String = "SegmentCreationList_Final"
Private Const SH_RAW      As String = "Raw Input"
Private Const SH_INSTR    As String = "Instructions"
Private Const SH_VALIDATE As String = "Straight to Validate"

'--- Fill In Sheet ------------------------------------------------------------
' B4:B14   "Checked?"        - 11 TRUE/FALSE checkbox cells                -> FALSE
' C4:L14   "Items To Explore (paste 1 per column, max 10)"                 -> cleared
' C19:H410 outcome checkboxes (C..H), extended from row 118 to row 410     -> FALSE
' I19:J410 "If Next stage, choose rsid" / "Notes" input cells              -> cleared
'          (K has no header on row 17 - it's not a real input column, so
'          it's intentionally left out of the clear range)
' NOT TOUCHED: M4:V14 helper formulas, A18 dynamic array formula
Private Const FI_CHECKED   As String = "B4:B14"
Private Const FI_ITEMS     As String = "C4:L14"
Private Const FI_OUTCOMES  As String = "C19:H410"
Private Const FI_NOTES     As String = "I19:J410"

'--- SegmentCreationList_Final -----------------------------------------------
' B3:B10    run parameters (prefix, segment dimensions/items) - B1 is
'          deliberately excluded, it now holds a live formula referencing
'          Raw Input and must never be cleared
' C4:C10   additional run parameters added since the original setup
' F14:G412 "Manual Skip" / "Special Flag" - empty input cells the LET formulas
'          in D/G/H read via $F14="x". Safe to clear; they hold no formulas.
Private Const SG_PARAMS  As String = "B3:B10"
Private Const SG_PARAMS2 As String = "C4:C10"
Private Const SG_FLAGS   As String = "F14:G412"

'--- Straight to Validate ------------------------------------------------------
' B1:B2 run parameters added since the original setup
Private Const SV_PARAMS As String = "B1:B2"

'--- Raw Input ---------------------------------------------------------------
' Columns A:S are the pasted export block per your spec.
'
' NOTE: the export actually writes A:W - T=segmentId, U=segmentHash,
' V=startDate, W=endDate. Clearing only A:S leaves those four behind, so stale
' dates/segment IDs from the previous run survive into the next one.
' Change RAW_LAST_COL to "W" to clear the whole pasted block.
'
' X:AA are helper formulas (Backup Column, SegmentVisits, AllTrafficVisits,
' rsid) and feed the pivot cache - they must NEVER be cleared.
Private Const RAW_FIRST_COL As String = "A"
Private Const RAW_LAST_COL  As String = "S"


'==============================================================================
' CleanFile
'==============================================================================
Public Sub CleanFile()

    Dim wb As Workbook
    Dim wsFillIn As Worksheet
    Dim wsSeg As Worksheet
    Dim wsRaw As Worksheet
    Dim lastRow As Long
    Dim savedCalc As XlCalculation
    Dim msg As String

    Set wb = ThisWorkbook

    msg = "Reset this workbook for the next bot rule run?" & vbCrLf & vbCrLf & _
          "This will permanently clear:" & vbCrLf & _
          "  - " & SH_FILLIN & ": " & FI_CHECKED & " and " & FI_OUTCOMES & _
          " reset to FALSE, " & FI_ITEMS & " and " & FI_NOTES & " emptied" & vbCrLf & _
          "  - " & SH_SEGLIST & ": " & SG_PARAMS & ", " & SG_PARAMS2 & " and " & SG_FLAGS & vbCrLf & _
          "  - " & SH_VALIDATE & ": " & SV_PARAMS & vbCrLf & _
          "  - " & SH_RAW & ": " & RAW_FIRST_COL & "2:" & RAW_LAST_COL & _
          " (all data rows)" & vbCrLf & vbCrLf & _
          "Only constant values are cleared - any formula living inside these " & _
          "ranges is skipped automatically. Pivot tables are not affected. " & _
          "This cannot be undone."

    If MsgBox(msg, vbExclamation + vbYesNo + vbDefaultButton2, "Clean File") <> vbYes Then Exit Sub

    savedCalc = Application.Calculation

    On Error GoTo Fail
    Application.ScreenUpdating = False
    Application.EnableEvents = False
    Application.DisplayAlerts = False
    Application.Calculation = xlCalculationManual

    '--- 1. Fill In Sheet ----------------------------------------------------
    Application.StatusBar = "Clearing " & SH_FILLIN & "..."
    Set wsFillIn = wb.Worksheets(SH_FILLIN)
    ClearConstantsOnly wsFillIn, FI_ITEMS
    wsFillIn.Range(FI_CHECKED).Value = False
    wsFillIn.Range(FI_OUTCOMES).Value = False
    ClearConstantsOnly wsFillIn, FI_NOTES

    '--- 2. SegmentCreationList_Final ---------------------------------------
    Application.StatusBar = "Clearing " & SH_SEGLIST & "..."
    Set wsSeg = wb.Worksheets(SH_SEGLIST)
    ClearConstantsOnly wsSeg, SG_PARAMS
    ClearConstantsOnly wsSeg, SG_PARAMS2
    ClearConstantsOnly wsSeg, SG_FLAGS

    '--- 3. Straight to Validate ---------------------------------------------
    Application.StatusBar = "Clearing " & SH_VALIDATE & "..."
    ClearConstantsOnly wb.Worksheets(SH_VALIDATE), SV_PARAMS

    '--- 4. Raw Input -------------------------------------------------------
    Application.StatusBar = "Clearing " & SH_RAW & " (this can take a moment)..."
    Set wsRaw = wb.Worksheets(SH_RAW)
    lastRow = RawInputLastRow(wsRaw)
    If lastRow >= 2 Then
        ClearConstantsOnly wsRaw, RAW_FIRST_COL & "2:" & RAW_LAST_COL & lastRow
    End If

    ' Park the cursor at the top of each sheet we touched
    On Error Resume Next
    wsRaw.Range("A1").Select
    On Error GoTo Fail

    Call RestoreApp(savedCalc)

    MsgBox "Workbook reset." & vbCrLf & vbCrLf & _
           "Cleared " & Format$(lastRow - 1, "#,##0") & " data rows from " & SH_RAW & "." & vbCrLf & _
           "Pivot tables still show the old data - run Refresh Pivots after pasting the new export.", _
           vbInformation, "Clean File"
    Exit Sub

Fail:
    Dim errDesc As String
    errDesc = Err.Description
    Call RestoreApp(savedCalc)
    MsgBox "Clean aborted: " & errDesc, vbCritical, "Clean File"

End Sub


'==============================================================================
' RefreshPivots
'
' One shared pivot cache (source: 'Raw Input'!A1:AA1048576) feeds all four
' pivot tables, so the cache refresh does the real work. The source range is
' full-height, so new rows are picked up automatically - no need to re-point it.
'==============================================================================
Public Sub RefreshPivots()

    Dim wb As Workbook
    Dim pc As PivotCache
    Dim ws As Worksheet
    Dim pt As PivotTable
    Dim nCaches As Long, nPivots As Long
    Dim savedCalc As XlCalculation

    Set wb = ThisWorkbook
    savedCalc = Application.Calculation

    On Error GoTo Fail
    Application.ScreenUpdating = False

    ' The cache reads the X:AA helper formulas on Raw Input, so those must be
    ' up to date BEFORE the cache is rebuilt.
    Application.StatusBar = "Recalculating helper columns..."
    Application.Calculation = xlCalculationAutomatic
    Application.Calculate

    Application.StatusBar = "Refreshing pivot cache(s) - this can take a while on a large export..."
    For Each pc In wb.PivotCaches
        ' Drop dimension items that no longer exist in the data, otherwise old
        ' Feature/rsid values linger in the pivot filters after a data swap.
        On Error Resume Next
        pc.MissingItemsLimit = xlMissingItemsNone
        On Error GoTo Fail

        pc.Refresh
        nCaches = nCaches + 1
    Next pc

    For Each ws In wb.Worksheets
        For Each pt In ws.PivotTables
            Application.StatusBar = "Refreshing " & ws.Name & " / " & pt.Name & "..."
            pt.RefreshTable
            nPivots = nPivots + 1
        Next pt
    Next ws

    Call RestoreApp(savedCalc)

    MsgBox "Refreshed " & nCaches & " pivot cache(s) and " & nPivots & " pivot table(s).", _
           vbInformation, "Refresh Pivots"
    Exit Sub

Fail:
    Dim errDesc As String
    errDesc = Err.Description
    Call RestoreApp(savedCalc)
    MsgBox "Refresh aborted: " & errDesc & vbCrLf & vbCrLf & _
           "You can refresh manually via PivotTable Analyze > Refresh > Refresh All.", _
           vbCritical, "Refresh Pivots"

End Sub


'==============================================================================
' Helpers
'==============================================================================

' Clears only the constant (non-formula) cells inside addr, leaving any
' formula untouched. Several of the "manual input" ranges in CleanFile have
' turned out to contain live formulas too (e.g. SegmentCreationList_Final!B1
' now references Raw Input) - this makes the clear resilient to that without
' needing to hand-carve out individual cells every time the sheet changes.
' SpecialCells raises an error if the range has no constants at all (e.g.
' every cell in it is now a formula); that's a no-op, not a failure.
Private Sub ClearConstantsOnly(ws As Worksheet, addr As String)

    On Error Resume Next
    ws.Range(addr).SpecialCells(xlCellTypeConstants).ClearContents
    On Error GoTo 0

End Sub


' Bottom of the Raw Input data. Uses the used range because the X:AA helper
' formulas run to the bottom of the block and column A can contain blanks.
Private Function RawInputLastRow(ws As Worksheet) As Long

    Dim r As Long, rUsed As Long

    r = ws.Cells(ws.Rows.Count, RAW_FIRST_COL).End(xlUp).Row

    On Error Resume Next
    If Not ws.UsedRange Is Nothing Then
        rUsed = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1
    End If
    On Error GoTo 0

    If rUsed > r Then r = rUsed
    If r < 2 Then r = 2
    If r > ws.Rows.Count Then r = ws.Rows.Count

    RawInputLastRow = r

End Function


Private Sub RestoreApp(savedCalc As XlCalculation)

    Application.StatusBar = False
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = savedCalc
    Application.ScreenUpdating = True

End Sub


'==============================================================================
' SetupTab - run once to build the Instructions tab and wire up the buttons.
' Safe to re-run: it rebuilds the tab in place.
'==============================================================================
Public Sub SetupTab()

    Dim wb As Workbook
    Dim ws As Worksheet
    Dim btn As Object
    Dim existed As Boolean

    Set wb = ThisWorkbook

    On Error GoTo Fail
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False

    On Error Resume Next
    Set ws = wb.Worksheets(SH_INSTR)
    On Error GoTo Fail

    If ws Is Nothing Then
        Set ws = wb.Worksheets.Add(Before:=wb.Worksheets(1))
        ws.Name = SH_INSTR
    Else
        existed = True
        ws.Cells.Clear
        ' Remove any buttons from a previous run so they do not stack up
        Dim shp As Shape
        For Each shp In ws.Shapes
            shp.Delete
        Next shp
        ws.Move Before:=wb.Worksheets(1)
    End If

    '--- Text ---------------------------------------------------------------
    With ws
        .Range("B2").Value = "Bot Rule Compare V2"
        .Range("B2").Font.Size = 16
        .Range("B2").Font.Bold = True

        .Range("B4").Value = "1. Clean File"
        .Range("B4").Font.Bold = True
        .Range("B5").Value = "Resets the workbook for the next bot rule run:"
        .Range("B6").Value = "    - " & SH_FILLIN & ": checkboxes back to FALSE, 'Items To Explore' and notes emptied"
        .Range("B7").Value = "    - " & SH_SEGLIST & ": run parameters (" & SG_PARAMS & ", " & SG_PARAMS2 & _
                             ") and manual flags (" & SG_FLAGS & ")"
        .Range("B8").Value = "    - " & SH_VALIDATE & ": run parameters (B1:B2)"
        .Range("B9").Value = "    - " & SH_RAW & ": all pasted data rows in columns " & _
                             RAW_FIRST_COL & ":" & RAW_LAST_COL
        .Range("B10").Value = "Formulas and pivot tables are left intact. Asks for confirmation first."

        .Range("B12").Value = "2. Paste the new export into '" & SH_RAW & "' starting at A2."
        .Range("B12").Font.Bold = True

        .Range("B14").Value = "3. Refresh Pivots"
        .Range("B14").Font.Bold = True
        .Range("B15").Value = "Recalculates the helper columns, then rebuilds the shared pivot cache"
        .Range("B16").Value = "and refreshes all pivot tables. Can take a while on a large export."

        .Columns("A").ColumnWidth = 3
        .Columns("B").ColumnWidth = 95
        .Range("B2").Select
    End With

    '--- Buttons ------------------------------------------------------------
    Set btn = ws.Buttons.Add(ws.Range("H5").Left, ws.Range("H5").Top, 150, 34)
    With btn
        .Name = "btnCleanFile"
        .Caption = "Clean File"
        .OnAction = "CleanFile"
    End With

    Set btn = ws.Buttons.Add(ws.Range("H15").Left, ws.Range("H15").Top, 150, 34)
    With btn
        .Name = "btnRefreshPivots"
        .Caption = "Refresh Pivots"
        .OnAction = "RefreshPivots"
    End With

    Application.DisplayAlerts = True
    Application.ScreenUpdating = True

    MsgBox IIf(existed, "'" & SH_INSTR & "' tab rebuilt.", "'" & SH_INSTR & "' tab created.") & _
           vbCrLf & "Both buttons are wired up and ready to use.", vbInformation, "Setup"
    Exit Sub

Fail:
    Dim errDesc As String
    errDesc = Err.Description
    Application.DisplayAlerts = True
    Application.ScreenUpdating = True
    MsgBox "Setup aborted: " & errDesc, vbCritical, "Setup"

End Sub
