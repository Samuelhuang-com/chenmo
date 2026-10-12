# next-steps-mod

每回合結束後,在輸入框上方建議最多三個「下一步」提示。按 1/2/3 填入輸入框(可再編輯),按 0 關閉。
也會把第一個建議當作輸入框的 Tab 灰字提示。只有你按了才會送出,外掛不會自動送出。

改寫自 MIT 授權的 `next-steps`(Thariq Shihipar),含 suggestSkills 選項(PR #2397),
並加上「用使用者正在使用的語言寫建議」。

## 安裝(本機終端機)
    claude plugin marketplace add C:\OneDrive\App\chenmo\next-steps-mod
    claude plugin install next-steps-mod@samuel-mods

## 設定
- minAnswerChars (預設 80):回答短於此字數不建議
- suggestSkills (預設 true):讓建議可以是技能 / 斜線指令

建議只在終端機版顯示(畫在 AbovePrompt)。
