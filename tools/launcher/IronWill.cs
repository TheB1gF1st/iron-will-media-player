// IronWill.exe: a tiny native launcher, so Windows (Default apps, Open with, Start menu, taskbar) sees a real
// program with Iron Will's name and icon. It just starts Python with IronWill.pyw and passes the file along.
// Build: E:\PythonMedia\python.exe tools\build_launcher.py
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Iron Will Media Player")]
[assembly: AssemblyDescription("Iron Will Media Player")]
[assembly: AssemblyProduct("Iron Will Media Player")]
[assembly: AssemblyCompany("Iron Will")]
[assembly: AssemblyCopyright("Iron Will")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

static class Launcher
{
    const string DefaultPython = @"E:\PythonMedia\pythonw.exe";

    [STAThread]
    static void Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(dir, "IronWill.pyw");
        // Optional override: put the path to pythonw.exe in python-path.txt next to this launcher.
        string python = DefaultPython;
        string cfg = Path.Combine(dir, "python-path.txt");
        if (File.Exists(cfg) && File.ReadAllText(cfg).Trim().Length > 0)
            python = File.ReadAllText(cfg).Trim();
        else if (!File.Exists(python))
            python = "pythonw.exe";  // other PCs: whatever Python is on the PATH

        var cmd = new StringBuilder("\"" + script + "\"");
        foreach (string a in args)
            cmd.Append(" \"").Append(a.Replace("\"", "\\\"")).Append('"');
        try
        {
            Process.Start(new ProcessStartInfo(python, cmd.ToString()) { UseShellExecute = false, WorkingDirectory = dir });
        }
        catch (Exception e)
        {
            MessageBox.Show("Iron Will couldn't start Python:\n" + python + "\n\n" + e.Message, "Iron Will Media Player",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
