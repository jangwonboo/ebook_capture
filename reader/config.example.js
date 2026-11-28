// Copy to config.local.js and fill in. config.local.js is ignored by git, so addresses stay on this PC.
// The settings dialogs in the reader override these per browser.
window.YeobaekConfig = {
  kindle: {
    method: 'email', // 'email' (Gmail compose window) or 'web' (Send to Kindle page)
    sender: 'name@gmail.com', // must be on Amazon's approved personal document e-mail list
    receiver: 'name@kindle.com',
  },
  drive: {
    folder: 'https://drive.google.com/drive/folders/FOLDER_ID', // the folder To Google Drive opens
    account: 'name@gmail.com', // the Google account to open it in
  },
};
