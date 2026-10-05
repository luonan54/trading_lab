# Sharing a clean project copy

[Back to README](../README.md)

These instructions apply when preparing a separate sharing copy. Do not reinitialize an existing checkout when updating this repository.

## Manual upload to YOUR personal GitHub

**First verify that you own the code and may share it.** Removing identifiers
or keys does not grant publishing rights to employer or third-party code. Use
only an approved GitHub Desktop installation on a managed computer, or follow
your organization's approved process on an authorized personal computer.
This exporter installs nothing and does not bypass device or network policy.

### GitHub Desktop (recommended)

1. **Copy this export folder outside every existing Git checkout first**, for
   example into a new folder under your personal Documents directory. The
   exporter's default `exports/` location is still inside the original worktree;
   Desktop may otherwise discover its parent repository. Never add or publish
   the original project, worktree, or its `.git` file.
2. In Desktop Settings/Preferences -> Accounts, verify the signed-in GitHub.com
   account is your **personal account**. Under Git, verify the commit author
   name/email; a personal GitHub noreply email avoids exposing a work email.
   Account sign-in and commit identity are separate settings.
3. File -> Add Local Repository -> select this exported folder. It has no `.git`;
   use the offered **Create a Repository here** action. Check the displayed
   final local path is exactly this folder, not an empty nested folder.
   Do not initialize from, copy, or attach the original Git history.
   If Desktop shows old commits, an existing remote, or the original project's
   path, stop: that is not the fresh sharing repository.
4. Review the initial Changes list file by file. `.env`, actual `config/*.yaml`,
   databases, logs and holdings must not appear. `.env.example` must have blank
   credential values. Do not force-add ignored files. Do not commit screenshots
   or real scan/portfolio outputs.
5. Commit the reviewed sharing files, then choose Publish Repository. Confirm
   the owner is your personal username (not an employer organization) and keep
   **Keep this code private** selected for the first publication.
6. Verify the repository URL and Files/Commits in your browser. Check again before
   later changing visibility to public. A private repository is still an upload.

If Desktop does not offer in-place creation, create a new empty personal
repository in Desktop and copy the **contents of this export only**, including
`.gitignore` and `.env.example`, into it. Do not copy the original app folder.

### Browser alternative

On GitHub.com verify your personal login, create a new private repository under
your personal owner, then Add file -> Upload files. Upload this export's contents,
preserving subdirectories, in batches if required. Uploading a ZIP stores a ZIP;
GitHub does not unpack it into a runnable repository.

Finder Cmd+Shift+. shows hidden files. Ensure `.gitignore` and `.env.example`
are included (create them manually in the GitHub editor if the picker omits
them). Do not upload the local `.env` or actual configs. GitHub Desktop handles
these hidden files and folder structure more reliably.

## Safety after publishing

The ignore rules prevent ordinary addition of private files; they do not protect
files already tracked, force-adds, edited examples, comments or commit messages.
Never paste real keys into a tracked file. If a key is ever committed or uploaded,
revoke/rotate it with the provider immediately; deleting the latest file does
not erase history or copies. Resolve repository history exposure separately.

For a later release, export to a new empty folder, review the changes, then copy
only reviewed code/example files into the personal repository. Do not copy
runtime data back into it. No license is automatically selected; choose one
only after confirming ownership and dependency obligations.
