using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

[assembly: AssemblyTitle("Forensic Tools")]
[assembly: AssemblyProduct("Forensic Tools Portable")]
[assembly: AssemblyVersion("1.0.0.0")]

static class Program
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibrary(string lpFileName);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr hModule, string procName);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string lpPathName);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int PyMainDelegate(
        int argc,
        [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] argv);

    [STAThread]
    static int Main(string[] args)
    {
        string exePath = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(exePath);
        string pyHome = Path.Combine(root, "runtime", "python");
        string toolsBin = Path.Combine(root, "runtime", "tools", "bin");
        string dllPath = Path.Combine(pyHome, "python311.dll");
        string mainPy = Path.Combine(root, "app", "main.py");

        Environment.SetEnvironmentVariable("FT_PORTABLE_ROOT", root);
        Environment.SetEnvironmentVariable("PYTHONHOME", pyHome);
        Environment.SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1");
        Environment.SetEnvironmentVariable("PYTHONNOUSERSITE", "1");
        Environment.SetEnvironmentVariable("PYTHONPATH", null);
        Environment.SetEnvironmentVariable("WEASYPRINT_DLL_DIRECTORIES", toolsBin);

        string oldPath = Environment.GetEnvironmentVariable("PATH") ?? "";
        Environment.SetEnvironmentVariable("PATH", toolsBin + ";" + pyHome + (oldPath.Length > 0 ? ";" + oldPath : ""));
        SetDllDirectory(pyHome);

        IntPtr hPy = LoadLibrary(dllPath);
        if (hPy == IntPtr.Zero)
        {
            MessageBox.Show(
                "Runtime Python (python311.dll) non trovato.\nVerifica che runtime\\python esista accanto a Forensic Tools.exe.",
                "Forensic Tools", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        IntPtr fn = GetProcAddress(hPy, "Py_Main");
        if (fn == IntPtr.Zero)
        {
            MessageBox.Show("Runtime Python non valido (Py_Main mancante).", "Forensic Tools", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        var pyMain = (PyMainDelegate)Marshal.GetDelegateForFunctionPointer(fn, typeof(PyMainDelegate));
        if (args.Length == 0)
        {
            var defaultArgs = new[] { exePath, "-I", mainPy };
            return pyMain(defaultArgs.Length, defaultArgs);
        }

        var fullArgs = new string[args.Length + 1];
        fullArgs[0] = exePath;
        Array.Copy(args, 0, fullArgs, 1, args.Length);
        return pyMain(fullArgs.Length, fullArgs);
    }
}
