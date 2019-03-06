# This is a template
# Saved as .py for easier editing
from __future__ import unicode_literals

# pylint: disable=import-error, no-name-in-module, too-many-format-args, undefined-variable, invalid-sequence-index
import subprocess
import os
import urllib

from uds import tools  # @UnresolvedImport

theFile = '''{m.r.as_file}'''

# First, try to locate  Remote Desktop Connection (version 2, from Microsoft website, not the app store one)

filename = tools.saveTempFile(theFile)
msrdc = '/Applications/Remote Desktop Connection.app/Contents/MacOS/Remote Desktop Connection'
cord = "/Applications/CoRD.app/Contents/MacOS/CoRD"

if os.path.isfile(cord):
    executable = cord
elif os.path.isfile(msrdc):
    executable = msrdc
else:
    executable = None


def onExit():
    import subprocess  # @Reimport
    subprocess.call(
        [
            'security',
             'delete-generic-password',
             '-a', '{m.usernameWithDomain}',
             '-s', 'Remote Desktop Connection 2 Password for {m.ip}',
        ]
    )


if executable is None:
    raise Exception('''<p><b>Microsoft Remote Desktop Connection not found</b></p>
<p>In order to connect to UDS RDP Sessions, you need to have at least one of the following:<p>
<ul>
    <li>
        <p><b>CoRD</b> (A bit unstable from 10.7 onwards)</p>
        <p>You can get it from <a href="{m.this_server}static/other/CoRD.pkg">this link</a></p>
    </li>
</ul>
<p>If both apps are installed, Remote Desktop Connection will be used as first option</p>

''')
elif executable == msrdc:
    try:
        if {m.hasCredentials}:  # @UndefinedVariable
            subprocess.call(
                [
                    'security',
                    'add-generic-password',
                    '-w', '{m.password}',
                    '-U',
                    '-a', '{m.usernameWithDomain}',
                    '-s', 'Remote Desktop Connection 2 Password for {m.ip}',
                    '-T', '/Applications/Remote Desktop Connection.app',
                ]
            )
            tools.addExecBeforeExit(onExit)
        # Call and wait for exit
        tools.addTaskToWait(subprocess.Popen([executable, filename]))

        tools.addFileToUnlink(filename)
    except Exception as e:
        raise
else:  # CoRD
    url = 'rdp://'

    username, domain = '{m.username}', '{m.domain}'

    if username != '':
        url += urllib.quote(username)
        if '{m.password}' != '':
            url += ':' + urllib.quote('{m.password}')
        url += '@'
    url += '{m.ip}/'
    if domain != '':
        url += domain

    url += '?screenDepth={m.r.bpp}'

    if {m.r.fullScreen}:  # @UndefinedVariable
        url += '&fullscreen###true'
    else:
        url += 'screenWidth###{m.r.width}&screenHeight###{m.r.height}'

    url += '&forwardAudio###' + '01'[{m.r.redirectAudio}]  # @UndefinedVariable

    if '{m.r.redirectDrives}' != 'false':  # @UndefinedVariable
        url += '&forwardDisks###true'

    if {m.r.redirectPrinters}:  # @UndefinedVariable
        url += '&forwardPrinters###true'

    tools.addTaskToWait(subprocess.Popen(['open', url]))
