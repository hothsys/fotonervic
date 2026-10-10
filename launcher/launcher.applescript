-- Source for the <APP_NAME>.app launcher. Rebuild with: launcher/build-app.sh
-- The display name (APP_TITLE, falling back to APP_NAME) is read from app.conf
-- at run time, not compiled in.
--
-- An AppleScript applet (rather than a plain shell-script bundle) is used so
-- macOS can prompt for Downloads/removable-volume access. The server started
-- here inherits the applet's privacy permissions.
--
-- The running dialog uses dialog.icns (the bare logo on a transparent
-- background) rather than applet.icns, whose rounded-square backdrop shows up
-- as a white box in the dialog.

on run
	set appPath to POSIX path of (path to me)
	set projectDir to do shell script "dirname " & quoted form of appPath
	set bundleName to do shell script "basename " & quoted form of appPath & " .app"

	-- Gatekeeper runs a quarantined app from a temporary read-only copy (App
	-- Translocation), where app.conf and server.sh next to it can't be found
	if appPath contains "/AppTranslocation/" then
		display dialog bundleName & " can't find its project folder." & return & return & ¬
			"macOS is running it from a temporary copy because the project was downloaded or copied with a quarantine flag." & return & return & ¬
			"To fix it, open Terminal in the project folder and run:" & return & return & ¬
			"    launcher/build-app.sh" & return & return & ¬
			"Then open the app again." with title bundleName buttons {"OK"} default button "OK" with icon caution
		return
	end if
	try
		do shell script "test -f " & quoted form of (projectDir & "/app.conf")
	on error
		display dialog bundleName & " can't find app.conf in:" & return & return & projectDir & return & return & ¬
			"Keep the app in the project folder, next to app.conf and server.sh." with title bundleName buttons {"OK"} default button "OK" with icon caution
		return
	end try

	set ctl to quoted form of (projectDir & "/server.sh")
	set envPrefix to "export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; "
	set appTitle to do shell script "cd " & quoted form of projectDir & " && . ./app.conf && printf %s \"${APP_TITLE:-$APP_NAME}\""

	try
		set statusText to do shell script envPrefix & ctl & " status"
	on error
		set statusText to ""
	end try

	if statusText is not "" then
		set serverURL to do shell script "echo " & quoted form of statusText & " | grep -o 'http://[^ ]*'"
		set choice to button returned of (display dialog appTitle & " is running at " & serverURL with title appTitle buttons {"Stop " & appTitle, "Open in Browser"} default button "Open in Browser" with icon (path to resource "dialog.icns"))
		if choice is "Open in Browser" then
			open location serverURL
		else
			do shell script envPrefix & ctl & " stop"
		end if
		return
	end if

	try
		do shell script envPrefix & ctl & " start 2>&1"
	on error errMsg
		display dialog appTitle & " failed to start:" & return & return & errMsg with title appTitle buttons {"OK"} default button "OK" with icon stop
	end try
end run
