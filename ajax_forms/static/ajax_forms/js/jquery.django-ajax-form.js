(function($){
     
    $.fn.django_ajax_form = function(options){
         
        options = $.extend({}, $.fn.django_ajax_form.defaults, options);
        
        function reset(el){
            el.val(el.data('initial_value'));
        }
        
        return this.each(function(){
            var form = $(this);
            var model_name = form.attr('delete_model');
              
            // Bind our custom post-validation callback
            // to each form field that's marked to be immediately saved
            // server side.
            var ajax_setter_els = $('[ajax-set-url]', form);
            for(var i=0; i<ajax_setter_els.length; i+=1){
                var el = $(ajax_setter_els[i]);
                //console.log(el.attr('name'));
                if(!options['rules'][el.attr('name')]){
                    options['rules'][el.attr('name')] = {};
                }
                options['rules'][el.attr('name')]['onComplete'] = $.fn.django_ajax_form.onComplete;
            }
            
            // Save initial form field values so we can selectively
            // reset them if needed.
            var form_fields = $('input, select', form);
            for(var i=0; i<form_fields.length; i+=1){
                var el = $(form_fields[i]);
                el.data('initial_value', el.val());
            }
            
            // Call jquery.validate() on our form.
            form.validate(options);
            form.data('options', options);
            
            // Forms that will be saved client side on a per-field basis
            // will never be submitted as a whole.
            form.submit(function(){
                return false;
            });
            
            // Bind model deletion links.
            $('.ajax-delete-link:not([ajax-delete-link-bound])').each(function(i){
                var el = $(this);
                el.attr('ajax-delete-link-bound', true);
                el.click(function(){
                    //console.log('clicked')
                    var el = $(this);
                    //return false;
                    var model_name = el.attr('ajax-model');
                    if(confirm('Delete '+model_name+'?')){
                        $.ajax({
                            url:el.attr('ajax-url'),
                            type:'POST',
                            dataType:'json'
                        })
                        .done(function(data){
                            if(data['success']){
                                $('[delete_id='+data['delete_id']+'][delete_model='+data['delete_model']+']')
                                    .fadeOut('slow', function(){
                                        var el = $(this);
                                        el.remove();
                                    });
                            }else{
                                alert('Deletion was unsuccessful.');
                            }
                            return false;
                        })
                        .fail(function(data){
                            alert('A problem occurred during deletion. Please try again later.');
                            return false;
                        });
                    }
                    return false;
                });
            });
            
            // Bind checkboxes to our customer onComplete callback, since
            // these are otherwise ignored by jquery.validate().
            $('input[type=checkbox]', form).change(function(){
                var el = $(this);
                var form = el.closest('form');
                form.data('options')['rules'][el.attr('name')]['onComplete'](el);
            });
            
            // Bind special create submit button.
            $('input[type=submit][create_button]', form).click(function(){
                //console.log('clicked');
                var button = $(this);
                var form = $(this).closest('form');
                var submit_url = button.attr('ajax-url') || form.attr('action');
                var prefix = button.attr('ajax-prefix');
                var valid = true;
                var els = $('[name^="'+prefix+'"]', form);
                var data = {};
                for(var i=0; i<els.length; i+=1){
                    var el = $(els[i]);
                    if(el.valid){
                        el.valid();
                    }
                    if(el.attr('type') != 'checkbox' && el.attr('type') != 'hidden' && !el.hasClass('valid')){
                        el.addClass('error');
                        valid = false;
                        //console.log('invalid:'+el.attr('name'));
                    }
                    data[el.attr('name')] = el.val();
                }
                //console.log('valid:'+valid)
                //console.log('data:'+data.length)
                //return
                if(!valid){
                    return;
                }
                $.ajax({
                    url:submit_url,
                    type:form.attr('method'),
                    data:data,
                    dataType:'json'
                })
                .done(function(data){
                    if(data['success']){
                        //form[0].reset();
                        for(var i=0; i<els.length; i+=1){
                            var el = $(els[i]);
                            reset(el);
                        }
                        method = data['method'] || 'insert';
                        if(method == 'insert'){
                            var insert_element = form.attr('insert_element');
                            $(insert_element).prepend(data['html']);
                        }else if(method == 'replace'){
                            var container_class = form.attr('container_class');
                            var delete_id = form.attr('delete_id');
                            var delete_model = form.attr('delete_model');
                            $('[delete_id='+delete_id+'][delete_model='+delete_model+'].'+container_class).replaceWith(data['html']);
                        }
                    }else{
                        alert('Unable to create record. Please try again later.');
                    }
                    return false;
                })
                .fail(function(data){
                    alert('A problem occurred during creation. Please try again later.');
                    return false;
                });
            });
            
        })
    }
     
     $.fn.django_ajax_form.onComplete = function(el){
        // Called after jquery.validate() finishes checking
        // a single form field.
        var el = $(el || this);
        var is_valid = el.hasClass('valid') || el.is('[type=checkbox]');
        var ajax_set_url = el.attr('ajax-set-url');
        var is_focussed = el.is(':focus');
        var value = (el.is('[type=checkbox]'))?el.is(':checked'):el.val();
        if(!is_focussed && is_valid && ajax_set_url){
            $.ajax({
                url:ajax_set_url,
                type:'POST',
                data:{value:value},
                dataType:'json'
            })
            .done(function(data){
                el.val(data['value']);
                var original_color = el.attr('ajax-original-color');
                var form = el.closest('form');
                if(original_color == null){
                    var original_color = el.css('border-color');
                    el.attr('ajax-original-color', original_color);
                }
                if(data.callback){
                    $(form).data(data.callback)();
                }
                el.css('border-color', '#0d0');
                el.animate({ 'border-color': original_color }, 3000);
                return false;
            })
            .fail(function(data){
                el.val(data['value']);
                return false;
            });
        }
    }
    
    $.fn.django_ajax_form.defaults = {
        rules:{}
    };
    
})(jQuery);
