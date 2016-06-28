%from bottle import request
%from alignak_webui import _

%#Set default values
%setdefault('debug', False)
%setdefault('js', [])
%setdefault('css', [])
%setdefault('title', _('Untitled...'))

%setdefault('panel', None)
<!DOCTYPE html>
<html lang="en">
   <head>
      <!--
         %# Web UI application about content
         %from bottle import request
         %from alignak_webui import manifest
         This file is a part of {{request.app.config.get('name', 'WebUI')}}.

         {{request.app.config.get('about_name', manifest['name'])}} {{request.app.config.get('about_version', manifest['version'])}}, &copy;&nbsp;{{request.app.config.get('about_copyright', manifest['copyright'])}}
      -->

      <!--[if lt IE 9]>
      <script src="http://html5shim.googlecode.com/svn/trunk/html5.js"></script>
      <![endif]-->

      <meta charset="utf-8">
      <meta http-equiv="X-UA-Compatible" content="IE=edge">
      <meta name="viewport" content="width=device-width, initial-scale=1">

      <title>{{title}}</title>

      <link href="/static/images/favicon.ico" rel="shortcut icon">

      <!-- Stylesheets
      ================================================== -->
      <link rel="stylesheet"href="/static/css/bootstrap.min.css" >
      <link rel="stylesheet"href="/static/css/bootstrap-theme.min.css" >
      <link rel="stylesheet"href="/static/css/font-awesome.min.css" >
      <link rel="stylesheet" href="/static/css/alertify.css" >

      <link rel="stylesheet" href="/static/css/alignak_webui.css" >
      <link rel="stylesheet" href="/static/css/alignak_webui-items.css" >

      %# Specific CSS files
      %for f in css:
      <link rel="stylesheet" href="/static/plugins/{{f}}">
      %end

      <!-- Scripts
      ================================================== -->
      <script type="text/javascript" src="/static/js/jquery-1.12.0.min.js"></script>
      <script type="text/javascript" src="/static/js/jquery-ui-1.11.4.min.js"></script>
      <script type="text/javascript" src="/static/js/bootstrap.min.js"></script>

      <!-- Specific scripts ... -->
      %# Specific Js files ...
      %for f in js:
      <script type="text/javascript" src="/static/plugins/{{f}}"></script>
      %end
   </head>

   <body>
      <div id="page-wrapper" class="container-fluid">
         <div class="row">
            <div id="page-content" class="col-lg-12">

               <!-- Page content -->
               <section class="content">
                  {{! panel}}
               </section>
            </div>
         </div>
      </div>
      %include("_footer", commands=True)
   </body>
</html>
