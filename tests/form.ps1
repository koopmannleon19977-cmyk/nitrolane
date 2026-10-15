Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form -Property @{Text = 'nitrolane fixture'; Width = 420; Height = 260; StartPosition = 'CenterScreen'}
$tb = New-Object Windows.Forms.TextBox -Property @{Left = 20; Top = 20; Width = 250; AccessibleName = 'Customer name'}
$cb = New-Object Windows.Forms.ComboBox -Property @{Left = 20; Top = 55; Width = 250; DropDownStyle = 'DropDownList'; AccessibleName = 'Country'}
[void]$cb.Items.AddRange(@('Deutschland', 'Österreich', 'Schweiz'))
$ok = New-Object Windows.Forms.Button -Property @{Left = 20; Top = 95; Width = 120; Text = 'Submit'}
$del = New-Object Windows.Forms.Button -Property @{Left = 150; Top = 95; Width = 150; Text = 'Delete all data'}
$lbl = New-Object Windows.Forms.Label -Property @{Left = 20; Top = 140; Width = 360; Text = 'Waiting'}
$ok.Add_Click({ $lbl.Text = "Hallo $($tb.Text) aus $($cb.SelectedItem)" })
$del.Add_Click({ $lbl.Text = 'DELETED' })
$f.Controls.AddRange(@($tb, $cb, $ok, $del, $lbl))
$t = New-Object Windows.Forms.Timer -Property @{Interval = 90000}
$t.Add_Tick({ $f.Close() })
$t.Start()
[void]$f.ShowDialog()
